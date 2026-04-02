"""Alarm and ticket business logic."""
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alarm import (
    Alarm, AlarmSeverity, AlarmStatus, AlarmType,
    Ticket, TicketPriority, TicketStatus, Technician,
)
from app.models.onu import ONU
from app.models.olt import OLT
from app.notifications.email_service import send_email
from app.notifications.sms_service import send_sms

logger = structlog.get_logger()

# Rx power thresholds (dBm)
RX_MINOR_THRESHOLD    = -26.0
RX_MAJOR_THRESHOLD    = -27.0
RX_CRITICAL_THRESHOLD = -28.0


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rx_severity(rx_power: float) -> AlarmSeverity | None:
    if rx_power <= RX_CRITICAL_THRESHOLD:
        return AlarmSeverity.CRITICAL
    if rx_power <= RX_MAJOR_THRESHOLD:
        return AlarmSeverity.MAJOR
    if rx_power <= RX_MINOR_THRESHOLD:
        return AlarmSeverity.MINOR
    return None


async def get_active_alarm(
    db: AsyncSession, onu_id: int, alarm_type: AlarmType
) -> Alarm | None:
    result = await db.execute(
        select(Alarm).where(
            Alarm.onu_id == onu_id,
            Alarm.alarm_type == alarm_type,
            Alarm.status == AlarmStatus.ACTIVE,
        )
    )
    return result.scalar_one_or_none()


async def create_alarm_and_ticket(
    db: AsyncSession,
    onu: ONU,
    olt: OLT,
    alarm_type: AlarmType,
    severity: AlarmSeverity,
    rx_power: float | None = None,
) -> tuple[Alarm, Ticket]:
    now = _now()
    alarm = Alarm(
        onu_id=onu.id,
        alarm_type=alarm_type,
        severity=severity,
        status=AlarmStatus.ACTIVE,
        rx_power=rx_power,
        detected_at=now,
    )
    db.add(alarm)
    await db.flush()  # get alarm.id

    if alarm_type == AlarmType.LOS:
        title = f"LOS — ONU {onu.serial_number} | Customer {onu.customer_id}"
        description = (
            f"Loss of Signal detected on ONU {onu.serial_number}\n"
            f"OLT: {olt.name} ({olt.host})\n"
            f"Port: {onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}\n"
            f"Customer: {onu.customer_id}\n"
            f"Detected: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        priority = TicketPriority.HIGH
    else:
        title = f"Low Rx — ONU {onu.serial_number} | {rx_power} dBm | Customer {onu.customer_id}"
        description = (
            f"Low Rx optical power detected on ONU {onu.serial_number}\n"
            f"Rx Power: {rx_power} dBm  (threshold: {RX_MINOR_THRESHOLD} dBm)\n"
            f"OLT: {olt.name} ({olt.host})\n"
            f"Port: {onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}\n"
            f"Customer: {onu.customer_id}\n"
            f"Detected: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        priority = TicketPriority.HIGH if severity == AlarmSeverity.CRITICAL else TicketPriority.MEDIUM

    ticket = Ticket(
        alarm_id=alarm.id,
        onu_id=onu.id,
        customer_id=onu.customer_id,
        title=title,
        description=description,
        status=TicketStatus.OPEN,
        priority=priority,
    )
    db.add(ticket)
    await db.flush()

    logger.info(
        "alarm_created",
        alarm_id=alarm.id,
        ticket_id=ticket.id,
        serial=onu.serial_number,
        alarm_type=alarm_type,
        severity=severity,
    )

    # Dispatch notifications to all active technicians
    await _dispatch_alarm_notifications(db, alarm, ticket, onu)
    return alarm, ticket


async def resolve_alarm(db: AsyncSession, alarm: Alarm) -> None:
    now = _now()
    alarm.status = AlarmStatus.RESOLVED
    alarm.resolved_at = now
    if alarm.ticket and alarm.ticket.status not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        alarm.ticket.status = TicketStatus.RESOLVED
        alarm.ticket.resolved_at = now
        alarm.ticket.resolution_notes = "Auto-resolved: ONU restored to normal state"
    await db.flush()
    logger.info("alarm_resolved", alarm_id=alarm.id, serial=alarm.onu.serial_number if alarm.onu else "?")


async def _dispatch_alarm_notifications(
    db: AsyncSession, alarm: Alarm, ticket: Ticket, onu: ONU
) -> None:
    result = await db.execute(
        select(Technician).where(Technician.active == True)
    )
    technicians = result.scalars().all()
    if not technicians:
        logger.warning("no_active_technicians_to_notify", alarm_id=alarm.id)
        return

    alarm_label = "LOSS OF SIGNAL (LOS)" if alarm.alarm_type == AlarmType.LOS else f"LOW Rx POWER ({alarm.rx_power} dBm)"
    sms_body = (
        f"[JTL ALARM] {alarm_label}\n"
        f"ONU: {onu.serial_number}\n"
        f"Customer: {onu.customer_id}\n"
        f"Port: {onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}\n"
        f"Ticket #{ticket.id}. Please respond."
    )
    email_subject = f"[JTL ALARM] {alarm_label} — Ticket #{ticket.id}"
    email_body = ticket.description or sms_body

    for tech in technicians:
        if tech.phone:
            await send_sms(tech.phone, sms_body)
        if tech.email:
            await send_email(tech.email, email_subject, email_body)


# ── CRUD helpers used by API endpoints ────────────────────────────────────────

async def list_alarms(
    db: AsyncSession, status: AlarmStatus | None = None, limit: int = 100
) -> list[Alarm]:
    q = select(Alarm).options(selectinload(Alarm.onu), selectinload(Alarm.ticket))
    if status:
        q = q.where(Alarm.status == status)
    q = q.order_by(Alarm.detected_at.desc()).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


async def list_tickets(
    db: AsyncSession, status: TicketStatus | None = None, limit: int = 100
) -> list[Ticket]:
    q = (
        select(Ticket)
        .options(
            selectinload(Ticket.onu).selectinload(ONU.olt),
            selectinload(Ticket.technician),
            selectinload(Ticket.alarm),
        )
        .order_by(Ticket.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Ticket.status == status)
    result = await db.execute(q)
    return result.scalars().all()


async def assign_ticket(
    db: AsyncSession, ticket_id: int, technician_id: int, notes: str | None
) -> Ticket:
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.technician)).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Ticket not found")

    tech_result = await db.execute(select(Technician).where(Technician.id == technician_id))
    tech = tech_result.scalar_one_or_none()
    if not tech:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Technician not found")

    ticket.assigned_to = technician_id
    ticket.status = TicketStatus.ASSIGNED
    ticket.assigned_at = _now()
    if notes:
        ticket.description = (ticket.description or "") + f"\n\nAssignment note: {notes}"
    await db.flush()

    # Notify the assigned technician
    if tech.phone:
        await send_sms(
            tech.phone,
            f"[JTL] Ticket #{ticket.id} assigned to you.\n{ticket.title}\nCustomer: {ticket.customer_id}"
        )
    if tech.email:
        await send_email(
            tech.email,
            f"[JTL] Ticket #{ticket.id} Assigned — {ticket.title}",
            ticket.description or ticket.title,
        )

    logger.info("ticket_assigned", ticket_id=ticket.id, technician_id=technician_id)
    await db.refresh(ticket)
    return ticket


async def resolve_ticket(
    db: AsyncSession, ticket_id: int, resolution_notes: str
) -> Ticket:
    result = await db.execute(
        select(Ticket).options(selectinload(Ticket.alarm)).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()
    if not ticket:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Ticket not found")

    now = _now()
    ticket.status = TicketStatus.RESOLVED
    ticket.resolved_at = now
    ticket.resolution_notes = resolution_notes

    if ticket.alarm and ticket.alarm.status == AlarmStatus.ACTIVE:
        ticket.alarm.status = AlarmStatus.RESOLVED
        ticket.alarm.resolved_at = now
        ticket.alarm.notes = resolution_notes

    await db.flush()
    logger.info("ticket_resolved", ticket_id=ticket.id)
    await db.refresh(ticket)
    return ticket


async def list_technicians(db: AsyncSession) -> list[Technician]:
    result = await db.execute(select(Technician).order_by(Technician.name))
    return result.scalars().all()


async def create_technician(db: AsyncSession, data) -> Technician:
    tech = Technician(**data.model_dump())
    db.add(tech)
    await db.flush()
    await db.refresh(tech)
    return tech


async def update_technician(db: AsyncSession, tech_id: int, data) -> Technician:
    result = await db.execute(select(Technician).where(Technician.id == tech_id))
    tech = result.scalar_one_or_none()
    if not tech:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Technician not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(tech, k, v)
    await db.flush()
    await db.refresh(tech)
    return tech


async def delete_technician(db: AsyncSession, tech_id: int) -> None:
    result = await db.execute(select(Technician).where(Technician.id == tech_id))
    tech = result.scalar_one_or_none()
    if not tech:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Technician not found")
    await db.delete(tech)
    await db.flush()
