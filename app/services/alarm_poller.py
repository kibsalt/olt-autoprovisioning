"""Background task: poll all OLTs for ONU alarms (LOS, low Rx).

Optimization strategy:
  - Group ONUs by (frame, slot, port) — one SSH call per port instead of per ONU.
  - Preload all active alarms for the OLT in a single query before processing.
  - Fall back to per-ONU detail-info if bulk commands are unsupported.
"""
import asyncio
import os
from collections import defaultdict

import structlog
from sqlalchemy import select

from app.config import settings
from app.db.session import async_session_factory
from app.models.alarm import Alarm, AlarmSeverity, AlarmStatus, AlarmType
from app.models.olt import OLT, OLTStatus
from app.models.onu import ONU
from app.olt_driver.driver_factory import OLTDriverPool
from app.services.alarm_service import (
    _rx_severity, create_alarm_and_ticket, resolve_alarm,
)

logger = structlog.get_logger()


async def _poll_once(driver_pool: OLTDriverPool) -> None:
    async with async_session_factory() as db:
        try:
            olt_result = await db.execute(
                select(OLT).where(OLT.status == OLTStatus.ACTIVE)
            )
            for olt in olt_result.scalars().all():
                try:
                    driver = await driver_pool.get_driver(olt)
                except Exception as e:
                    logger.warning("poller_olt_unreachable", olt=olt.name, error=str(e))
                    continue
                await _poll_olt(db, driver, olt)

            await db.commit()
        except Exception:
            logger.exception("poller_error")
            await db.rollback()


async def _poll_olt(db, driver, olt) -> None:
    # Load all enabled ONUs for this OLT
    onu_result = await db.execute(
        select(ONU).where(ONU.olt_id == olt.id)
    )
    onus = onu_result.scalars().all()
    if not onus:
        return

    # Preload all active alarms for this OLT in one query: {onu_id → {alarm_type → Alarm}}
    alarm_result = await db.execute(
        select(Alarm)
        .where(
            Alarm.onu_id.in_([o.id for o in onus]),
            Alarm.status == AlarmStatus.ACTIVE,
        )
    )
    active_alarms: dict[int, dict[AlarmType, Alarm]] = defaultdict(dict)
    for alarm in alarm_result.scalars().all():
        active_alarms[alarm.onu_id][alarm.alarm_type] = alarm

    # Group ONUs by port for bulk SSH queries
    by_port: dict[tuple, list[ONU]] = defaultdict(list)
    for onu in onus:
        by_port[(onu.frame, onu.slot, onu.port)].append(onu)

    for (frame, slot, port), port_onus in by_port.items():
        await _poll_port(db, driver, olt, frame, slot, port, port_onus, active_alarms)


async def _poll_port(db, driver, olt, frame, slot, port, onus, active_alarms) -> None:
    # ── Bulk state fetch (1 SSH call for the whole port) ────────────────────
    states: dict[int, str] = {}
    rx_map: dict[int, float] = {}

    if hasattr(driver, "get_port_onu_states"):
        try:
            states = await driver.get_port_onu_states(frame, slot, port)
        except Exception as e:
            logger.warning("poller_bulk_state_failed", port=f"{frame}/{slot}/{port}", error=str(e))

        try:
            rx_map = await driver.get_port_onu_rx(frame, slot, port)
        except Exception as e:
            logger.debug("poller_bulk_rx_failed", port=f"{frame}/{slot}/{port}", error=str(e))

    for onu in onus:
        oper_state = states.get(onu.onu_id, "")
        rx_power   = rx_map.get(onu.onu_id)

        # Fall back to per-ONU detail query if bulk returned nothing for this ONU
        if not oper_state and not states:
            from app.olt_driver.base import ONUIdentifier
            try:
                res = await driver.get_onu_status(
                    ONUIdentifier(frame=frame, slot=slot, port=port, onu_id=onu.onu_id)
                )
                parsed = res.parsed or {}
                oper_state = (parsed.get("oper_state") or "").lower()
                if parsed.get("rx_power") is not None:
                    try:
                        rx_power = float(parsed["rx_power"])
                    except (ValueError, TypeError):
                        pass
            except Exception as e:
                logger.warning("poller_status_failed", serial=onu.serial_number, error=str(e))
                continue

        existing = active_alarms.get(onu.id, {})

        # ── LOS ──────────────────────────────────────────────────────────────
        is_offline = oper_state and oper_state not in ("working", "online")
        if is_offline:
            if AlarmType.LOS not in existing:
                await create_alarm_and_ticket(db, onu, olt, AlarmType.LOS, AlarmSeverity.CRITICAL)
                logger.warning("alarm_los", serial=onu.serial_number, state=oper_state)
        else:
            if AlarmType.LOS in existing:
                await resolve_alarm(db, existing[AlarmType.LOS])
                logger.info("alarm_los_resolved", serial=onu.serial_number)

        # ── Low Rx ───────────────────────────────────────────────────────────
        if rx_power is not None:
            severity = _rx_severity(rx_power)
            if severity:
                if AlarmType.LOW_RX not in existing:
                    await create_alarm_and_ticket(db, onu, olt, AlarmType.LOW_RX, severity, rx_power)
                    logger.warning("alarm_low_rx", serial=onu.serial_number, rx=rx_power)
            else:
                if AlarmType.LOW_RX in existing:
                    await resolve_alarm(db, existing[AlarmType.LOW_RX])
                    logger.info("alarm_low_rx_resolved", serial=onu.serial_number, rx=rx_power)


async def run_alarm_poller(driver_pool: OLTDriverPool) -> None:
    # With uvicorn multi-worker, each process runs this. Use a DB lock so only
    # one worker polls at a time — the others back off immediately each cycle.
    interval = settings.alarm_poll_interval
    # Stagger workers by PID so they don't all wake at the same second
    await asyncio.sleep((os.getpid() % 10) * 3)
    logger.info("alarm_poller_started", interval_seconds=interval, pid=os.getpid())
    while True:
        acquired = False
        async with async_session_factory() as lock_db:
            try:
                # Attempt advisory lock (MySQL GET_LOCK — non-blocking)
                from sqlalchemy import text
                result = await lock_db.execute(
                    text("SELECT GET_LOCK('olt_alarm_poller', 0)")
                )
                acquired = bool(result.scalar())
            except Exception:
                acquired = False

        if acquired:
            try:
                await _poll_once(driver_pool)
            except Exception:
                logger.exception("alarm_poller_unhandled")
            finally:
                async with async_session_factory() as lock_db:
                    try:
                        from sqlalchemy import text
                        await lock_db.execute(text("SELECT RELEASE_LOCK('olt_alarm_poller')"))
                    except Exception:
                        pass

        await asyncio.sleep(interval)
