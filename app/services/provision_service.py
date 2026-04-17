"""BSS-facing flat provisioning service — full 14-step ONU workflow."""

# ONU models known to support WiFi configuration via OLT CLI (pon-onu-mng ssid ctrl/auth).
# All other models skip the OLT CLI step and rely on ACS/TR-069 for WiFi provisioning.
_WIFI_OLT_CLI_MODELS: frozenset[str] = frozenset({
    "ZTEG-F660",
    "ZTE-F660",
    "ZTE-F680",
    "ZTE-F609",
})
import time

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.olt import OLT
from app.models.onu import ONU, AdminState
from app.olt_driver.base import ONUIdentifier
from app.olt_driver.driver_factory import OLTDriverPool
from app.olt_driver.response_parser import OLTResponseParser
from app.notifications.notify import notify_customer_wifi_credentials
from app.schemas.provision import ProvisionRequest, ProvisionResponse
from app.services.olt_service import get_olt_or_404
from app.utils.acs_client import ACSClient
from app.utils.packages import kbps_to_profile_name, resolve_package
from app.utils.wifi import generate_wifi_credentials

logger = structlog.get_logger()


async def get_olt_by_name(db: AsyncSession, olt_name: str) -> OLT:
    result = await db.execute(select(OLT).where(OLT.name == olt_name))
    olt = result.scalar_one_or_none()
    if not olt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OLT '{olt_name}' not found. Check OLT inventory.",
        )
    return olt


def _acs() -> ACSClient:
    return ACSClient(settings.acs_management_url)


async def _find_onu_port(driver, serial_number: str, known_slots: list[tuple]) -> tuple | None:
    """Scan known GPON ports to find which port has the unconfigured ONU."""
    parser = OLTResponseParser()
    for frame, slot, port in known_slots:
        try:
            raw = await driver.discover_unregistered_onus(frame, slot, port)
            for onu in raw:
                if onu.get("serial_number", "").upper() == serial_number.upper():
                    return frame, slot, port
        except Exception:
            continue
    return None


async def bss_provision(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    data: ProvisionRequest,
) -> ProvisionResponse:
    t_start = time.monotonic()

    # 1. Resolve OLT by name
    olt = await get_olt_by_name(db, data.olt_id)

    # 2. Check for duplicate customer
    existing = await db.execute(select(ONU).where(ONU.customer_id == data.customer_id))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Customer '{data.customer_id}' is already provisioned.",
        )

    # 3. Get driver
    driver = await driver_pool.get_driver(olt)
    parser = OLTResponseParser()

    # 4. Resolve package → bandwidth
    kbps, _ = resolve_package(data.package_id)
    profile_name = kbps_to_profile_name(kbps)

    # 5. Locate ONU port — use caller-supplied location if known, else scan
    if data.known_frame is not None and data.known_slot is not None and data.known_port is not None:
        frame, slot, port = data.known_frame, data.known_slot, data.known_port
        logger.info(
            "bss_provision_using_known_port",
            serial=data.onu_serial_number,
            port=f"{frame}/{slot}/{port}",
        )
    else:
        # Default scan: slots 7 and 9, ports 0-15 (covers C300 8+16 port cards)
        scan_ports = [
            (1, s, p)
            for s in [7, 9]
            for p in range(16)
        ]
        location = await _find_onu_port(driver, data.onu_serial_number, scan_ports)
        if location is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"ONU {data.onu_serial_number} not found in unconfigured list on {data.olt_id}. "
                    f"Verify the ONU is powered on and connected to a PON port."
                ),
            )
        frame, slot, port = location

    # 6. Determine next ONU ID
    try:
        if olt.platform.value == "ZXAN":
            raw = await driver.ssh.execute(
                f"show running-config interface gpon-olt_{frame}/{slot}/{port}"
            )
        else:
            raw = await driver.ssh.execute(
                f"show running-config interface gpon_olt-{frame}/{slot}/{port}"
            )
        next_id = parser.parse_next_onu_id(raw)
        if next_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No available ONU IDs on this port (max 128 reached).",
            )
    except HTTPException:
        raise
    except Exception:
        next_id = 1

    onu_ident = ONUIdentifier(frame=frame, slot=slot, port=port, onu_id=next_id)

    # 7. Authorize ONU
    await driver.authorize_onu(
        onu_ident, data.onu_serial_number, data.onu_model, data.description
    )

    # 8+9. Configure T-CONT, GEM port and service-port in one batched config session
    if hasattr(driver, "configure_tcont_gemport_serviceport"):
        await driver.configure_tcont_gemport_serviceport(
            onu_ident,
            tcont_id=1,
            dba_profile_id=profile_name,
            gem_port=1,
            service_port_id=1,
            vlan_tag=data.service_vlan,
            svlan=data.svlan,
        )
    else:
        # Fallback for drivers that don't support the batched method
        await driver.configure_tcont(onu_ident, tcont_id=1, dba_profile_id=profile_name)
        await driver.configure_gemport(onu_ident, gem_port=1, tcont_id=1)
        await driver.create_service_port(
            1, onu_ident, data.service_vlan,
            gem_port=1, service_type="internet",
            svlan=data.svlan,
        )

    # 10. Push full OMCI profile via pon-onu-mng: flow, PPPoE, ACS/TR-069, security
    # Non-fatal — third-party ONUs or older firmware may not support pon-onu-mng
    try:
        await driver.configure_omci(
            onu_ident,
            vlan_id=data.service_vlan,
            acs_url=settings.acs_url,
            acs_username=settings.acs_username,
            acs_password=settings.acs_password,
            pppoe_username=data.pppoe_username,
            pppoe_password=data.pppoe_password,
        )
    except Exception as exc:
        logger.warning(
            "omci_profile_push_failed",
            serial=data.onu_serial_number,
            error=str(exc)[:300],
            detail="PPPoE passthrough via service-port VLAN still active; ACS will auto-configure",
        )

    # 11. Resolve final WiFi credentials
    # Use caller-supplied creds when provided (e.g. tech portal with JTL naming),
    # otherwise auto-generate from customer_id.
    if data.wifi_ssid_2g and data.wifi_ssid_5g and data.wifi_password:
        wifi = {
            "ssid_2g":  data.wifi_ssid_2g,
            "ssid_5g":  data.wifi_ssid_5g,
            "password": data.wifi_password,
        }
    else:
        wifi = generate_wifi_credentials(data.customer_id)

    # 11b. Push WiFi credentials to ONU via OLT CLI (pon-onu-mng ssid ctrl/auth).
    # Only attempted for ONU models known to support the ssid CLI commands.
    # All others (F839, HWTC, F601, etc.) skip directly to ACS SOAP (step 13).
    onu_model_key = (data.onu_model or "").upper().replace(" ", "-")
    wifi_via_olt = any(
        m.upper() in onu_model_key or onu_model_key in m.upper()
        for m in _WIFI_OLT_CLI_MODELS
    )
    if wifi_via_olt:
        try:
            await driver.configure_wifi(
                onu_ident,
                ssid_2g=wifi["ssid_2g"],
                ssid_5g=wifi["ssid_5g"],
                password=wifi["password"],
            )
        except Exception as exc:
            logger.warning(
                "wifi_olt_push_failed",
                serial=data.onu_serial_number,
                model=data.onu_model,
                error=str(exc)[:300],
                detail="WiFi OLT CLI push failed — ACS SOAP will still be attempted",
            )
    else:
        logger.info(
            "wifi_olt_skipped",
            serial=data.onu_serial_number,
            model=data.onu_model,
            reason="ONU model does not support WiFi via OLT CLI — using ACS only",
        )

    # 12. Save ONU to DB
    onu = ONU(
        olt_id=olt.id,
        serial_number=data.onu_serial_number,
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_email=data.customer_email,
        frame=frame,
        slot=slot,
        port=port,
        onu_id=next_id,
        onu_type=data.onu_model,
        description=data.description,
        wifi_ssid_2g=wifi["ssid_2g"],
        wifi_ssid_5g=wifi["ssid_5g"],
        wifi_password=wifi["password"],
        package_id=data.package_id,
        service_vlan=data.service_vlan,
        oam_vlan=data.oam_vlan,
        svlan=data.svlan,
        pppoe_username=data.pppoe_username,
        pppoe_password=data.pppoe_password,
    )
    db.add(onu)
    await db.flush()
    await db.refresh(onu)

    # 13. Push WiFi to ACS via SOAP ProvisionCustomer
    acs_informed = False
    phase_state_confirmed = False
    if data.service_id:
        from app.utils.acs_client import JTLACSClient
        jtl_acs = JTLACSClient(settings.acs_soap_url, settings.acs_soap_api_key)
        wifi_ok = await jtl_acs.provision_wifi(
            account_id=data.customer_id,
            service_id=data.service_id,
            onu_sn=data.onu_serial_number,
            ssid=wifi["ssid_2g"],
            password=wifi["password"],
        )
        acs_informed = wifi_ok
        phase_state_confirmed = wifi_ok
        if not wifi_ok:
            logger.warning("acs_soap_push_failed", serial=data.onu_serial_number)
    else:
        logger.info(
            "acs_soap_skipped",
            serial=data.onu_serial_number,
            reason="no service_id in request",
        )

    # 14. Send notifications
    notifications_sent = []
    try:
        await notify_customer_wifi_credentials(db, onu)
        if onu.customer_phone:
            notifications_sent.append("sms")
        if onu.customer_email:
            notifications_sent.append("email")
        if onu.customer_phone and settings.at_whatsapp_sender:
            notifications_sent.append("whatsapp")
    except Exception as exc:
        logger.warning("notification_failed", error=str(exc))

    duration_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "bss_onu_provisioned",
        customer_id=data.customer_id,
        serial=data.onu_serial_number,
        olt=data.olt_id,
        onu_location=f"{frame}/{slot}/{port}:{next_id}",
        package=data.package_id,
        duration_ms=duration_ms,
    )

    return ProvisionResponse(
        success=True,
        customer_id=data.customer_id,
        onu_db_id=onu.id,
        serial_number=data.onu_serial_number,
        olt_name=olt.name,
        onu_location=f"{frame}/{slot}/{port}:{next_id}",
        package_id=data.package_id,
        wifi_ssid_2g=wifi["ssid_2g"],
        wifi_ssid_5g=wifi["ssid_5g"],
        phase_state_confirmed=phase_state_confirmed,
        acs_informed=acs_informed,
        notifications_sent=notifications_sent,
        duration_ms=duration_ms,
    )


async def bss_deprovision(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    customer_id: str,
) -> None:
    from app.services.onu_service import find_onu_by_customer, remove_onu
    onus = await find_onu_by_customer(db, customer_id)
    if not onus:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No provisioned ONU found for customer '{customer_id}'.",
        )
    for onu in onus:
        await remove_onu(db, driver_pool, onu.olt_id, onu.id)
    logger.info("bss_onu_deprovisioned", customer_id=customer_id)


async def bss_suspend(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    customer_id: str,
) -> dict:
    from app.services.onu_service import find_onu_by_customer, set_onu_state
    onus = await find_onu_by_customer(db, customer_id)
    if not onus:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found.")
    for onu in onus:
        await set_onu_state(db, driver_pool, onu.olt_id, onu.id, AdminState.SUSPENDED)
    logger.info("bss_onu_suspended", customer_id=customer_id)
    return {"customer_id": customer_id, "state": "suspended"}


async def bss_activate(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    customer_id: str,
) -> dict:
    from app.services.onu_service import find_onu_by_customer, set_onu_state
    onus = await find_onu_by_customer(db, customer_id)
    if not onus:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found.")
    for onu in onus:
        await set_onu_state(db, driver_pool, onu.olt_id, onu.id, AdminState.ENABLED)
    logger.info("bss_onu_activated", customer_id=customer_id)
    return {"customer_id": customer_id, "state": "active"}


async def bss_change_package(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    customer_id: str,
    package_id: str,
) -> dict:
    from app.services.onu_service import find_onu_by_customer
    onus = await find_onu_by_customer(db, customer_id)
    if not onus:
        raise HTTPException(status_code=404, detail=f"Customer '{customer_id}' not found.")

    kbps, _ = resolve_package(package_id)
    profile_name = kbps_to_profile_name(kbps)

    for onu in onus:
        olt = await get_olt_or_404(db, onu.olt_id)
        driver = await driver_pool.get_driver(olt)
        onu_ident = ONUIdentifier(
            frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
        )
        await driver.configure_tcont(onu_ident, tcont_id=1, dba_profile_id=profile_name)
        onu.package_id = package_id
        await db.flush()

    logger.info("bss_package_changed", customer_id=customer_id, package=package_id)
    return {"customer_id": customer_id, "package_id": package_id, "bandwidth_kbps": kbps}
