import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.onu import ONU, AdminState, ONUService, ONUServiceStatus
from app.models.service_profile import ServiceProfile
from app.olt_driver.base import BaseOLTDriver, ONUIdentifier
from app.olt_driver.driver_factory import OLTDriverPool
from app.olt_driver.response_parser import OLTResponseParser
from app.schemas.onu import ONUCreate
from app.services.olt_service import get_olt_or_404
from app.utils.acs_client import ACSClient
from app.utils.wifi import generate_wifi_credentials

logger = structlog.get_logger()


def _acs_client() -> ACSClient:
    return ACSClient(settings.acs_management_url)


async def get_onu_or_404(db: AsyncSession, onu_db_id: int) -> ONU:
    result = await db.execute(select(ONU).where(ONU.id == onu_db_id))
    onu = result.scalar_one_or_none()
    if not onu:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ONU not found")
    return onu


async def list_onus(
    db: AsyncSession,
    olt_id: int,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ONU], int]:
    query = select(ONU).where(ONU.olt_id == olt_id)
    count_result = await db.execute(select(ONU.id).where(ONU.olt_id == olt_id))
    total = len(count_result.all())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return result.scalars().all(), total


async def find_onu_by_customer(
    db: AsyncSession, customer_id: str
) -> list[ONU]:
    result = await db.execute(
        select(ONU).where(ONU.customer_id == customer_id)
    )
    return result.scalars().all()


async def discover_unregistered(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    frame: int | None = None,
    slot: int | None = None,
    port: int | None = None,
) -> list[dict]:
    olt = await get_olt_or_404(db, olt_id)
    driver = await driver_pool.get_driver(olt)
    return await driver.discover_unregistered_onus(
        frame=frame or 1, slot=slot or 1, port=port or 1
    )


async def provision_onu(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    data: ONUCreate,
) -> ONU:
    olt = await get_olt_or_404(db, olt_id)

    # Reject duplicate serial numbers
    existing_sn = await db.execute(select(ONU).where(ONU.serial_number == data.serial_number))
    if existing_sn.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Serial number {data.serial_number} is already provisioned. Delete it first if you want to re-provision.",
        )

    driver = await driver_pool.get_driver(olt)

    parser = OLTResponseParser()
    onu_ident = ONUIdentifier(
        frame=data.frame, slot=data.slot, port=data.port, onu_id=0
    )

    # Determine next available ONU ID on the port
    # Also detect if this serial is already registered on the OLT (orphaned) — reuse its ID
    already_on_olt = False
    try:
        if olt.platform.value == "ZXAN":
            raw = await driver.ssh.execute(
                f"show running-config interface gpon-olt_{data.frame}/{data.slot}/{data.port}"
            )
        else:
            raw = await driver.ssh.execute(
                f"show running-config interface gpon_olt-{data.frame}/{data.slot}/{data.port}"
            )
        existing_id = parser.parse_onu_id_by_serial(raw, data.serial_number)
        logger.debug("provision_ssh_raw", serial=data.serial_number, raw_len=len(raw), raw_preview=raw[:200])
        if existing_id is not None:
            # SN already registered on OLT — reuse that ONU ID, skip re-authorization
            next_id = existing_id
            already_on_olt = True
        else:
            next_id = parser.parse_next_onu_id(raw)
            logger.debug("provision_next_id_from_ssh", serial=data.serial_number, next_id=next_id)
            if next_id is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No available ONU IDs on this port",
                )
            # Guard: SSH may return empty/stale output. If the derived ID is
            # already occupied in DB (from a previous provisioning), fall back
            # to DB to avoid a uq_onu_location collision.
            collision = await db.execute(
                select(ONU).where(
                    ONU.olt_id == olt_id,
                    ONU.frame == data.frame,
                    ONU.slot == data.slot,
                    ONU.port == data.port,
                    ONU.onu_id == next_id,
                )
            )
            collision_row = collision.scalar_one_or_none()
            logger.debug("provision_collision_check", serial=data.serial_number, next_id=next_id, collision_found=bool(collision_row))
            if collision_row:
                db_ids = await db.execute(
                    select(ONU.onu_id).where(
                        ONU.olt_id == olt_id,
                        ONU.frame == data.frame,
                        ONU.slot == data.slot,
                        ONU.port == data.port,
                    )
                )
                used_ids = {row[0] for row in db_ids.fetchall()}
                next_id = next((i for i in range(1, 129) if i not in used_ids), None)
                logger.debug("provision_db_fallback_after_collision", serial=data.serial_number, used_ids=list(used_ids), next_id=next_id)
                if next_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="No available ONU IDs on this port",
                    )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        # Running-config read failed — fall back to DB-based ID to avoid collision
        db_result = await db.execute(
            select(ONU.onu_id).where(
                ONU.olt_id == olt_id,
                ONU.frame == data.frame,
                ONU.slot == data.slot,
                ONU.port == data.port,
            )
        )
        used_ids = {row[0] for row in db_result.fetchall()}
        next_id = next((i for i in range(1, 129) if i not in used_ids), None)
        if next_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No available ONU IDs on this port",
            )

    onu_ident.onu_id = next_id
    vlan = data.service_vlan or 2918

    # 1. Authorize ONU on OLT (skip if already registered on OLT — orphaned from DB)
    if not already_on_olt:
        await driver.authorize_onu(
            onu_ident, data.serial_number, data.onu_type, data.description
        )
    else:
        logger.info(
            "onu_already_on_olt",
            serial=data.serial_number,
            onu_id=next_id,
            detail="Serial already registered on OLT — skipping authorize, syncing DB only",
        )

    # 2. Configure T-CONT & GEM Port (use named DBA profile)
    dba_profile = "Fix_10M"  # Default — TODO: derive from package_id
    try:
        await driver.configure_tcont(onu_ident, tcont_id=1, dba_profile_id=dba_profile)
        await driver.configure_gemport(
            onu_ident, gem_port=1, tcont_id=1, profile_name=dba_profile
        )
    except Exception as exc:
        logger.warning("tcont_gem_failed", serial=data.serial_number, error=str(exc)[:200])

    # 3. Create Service Port (VLAN)
    try:
        await driver.create_service_port(
            1, onu_ident, vlan, gem_port=1, service_type="internet",
        )
    except Exception as exc:
        logger.warning("service_port_failed", serial=data.serial_number, error=str(exc)[:200])

    # 4. Push full OMCI profile via pon-onu-mng: flow, PPPoE (via OLT), ACS, security
    # Non-fatal — third-party ONUs or older firmware may reject some commands
    try:
        await driver.configure_omci(
            onu_ident,
            vlan_id=vlan,
            acs_url=settings.acs_url,
            acs_username=settings.acs_username,
            acs_password=settings.acs_password,
            pppoe_username=data.pppoe_username,
            pppoe_password=data.pppoe_password,
        )
    except Exception as exc:
        logger.warning("omci_profile_push_failed", serial=data.serial_number, error=str(exc)[:200])

    # 5. Generate WiFi credentials
    wifi_ssid_2g = data.wifi_ssid_2g
    wifi_ssid_5g = data.wifi_ssid_5g
    wifi_password = data.wifi_password
    if not all([wifi_ssid_2g, wifi_ssid_5g, wifi_password]):
        creds = generate_wifi_credentials(data.customer_name)
        wifi_ssid_2g = wifi_ssid_2g or creds["ssid_2g"]
        wifi_ssid_5g = wifi_ssid_5g or creds["ssid_5g"]
        wifi_password = wifi_password or creds["password"]

    # 6. Save ONU to database
    onu = ONU(
        olt_id=olt_id,
        serial_number=data.serial_number,
        customer_id=data.customer_id,
        customer_name=data.customer_name,
        frame=data.frame,
        slot=data.slot,
        port=data.port,
        onu_id=next_id,
        onu_type=data.onu_type,
        description=data.description,
        service_vlan=vlan,
        pppoe_username=data.pppoe_username,
        pppoe_password=data.pppoe_password,
        wifi_ssid_2g=wifi_ssid_2g,
        wifi_ssid_5g=wifi_ssid_5g,
        wifi_password=wifi_password,
    )
    db.add(onu)
    await db.flush()
    await db.refresh(onu)

    # 7. Apply service profiles if provided
    if data.service_profile_ids:
        for sp_id in data.service_profile_ids:
            await apply_service_to_onu(db, driver, onu, sp_id)

    # 8. Push WiFi via ACS (best-effort — does not block provisioning)
    acs = _acs_client()
    wifi_ok = await acs.configure_wifi(
        data.serial_number, wifi_ssid_2g, wifi_ssid_5g, wifi_password
    )
    if not wifi_ok:
        logger.warning(
            "acs_wifi_failed",
            serial=data.serial_number,
            customer=data.customer_id,
        )

    logger.info(
        "onu_provisioned",
        onu_id=onu.id,
        serial=data.serial_number,
        customer=data.customer_id,
        olt=olt.name,
        vlan=vlan,
        wifi_2g=wifi_ssid_2g,
        wifi_5g=wifi_ssid_5g,
        pppoe_user=data.pppoe_username,
    )
    return onu


async def update_pppoe(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    onu_db_id: int,
    username: str,
    password: str,
    service_vlan: int | None = None,
) -> dict:
    onu = await get_onu_or_404(db, onu_db_id)
    if onu.olt_id != olt_id:
        raise HTTPException(status_code=404, detail="ONU not found on this OLT")

    olt = await get_olt_or_404(db, olt_id)
    driver = await driver_pool.get_driver(olt)

    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )
    path = f"gpon-onu_{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"

    # Build pon-onu-mng commands for PPPoE (and optionally VLAN flow update)
    vlan = service_vlan if service_vlan else onu.service_vlan or 2918
    commands = [
        f"pon-onu-mng {path}",
        f"pppoe 1 nat enable user {username} password {password}",
    ]
    if service_vlan:
        commands += [
            "flow mode 1 tag-filter vlan-filter untag-filter discard",
            f"flow 1 pri 0 vlan {service_vlan}",
            f"vlan-filter-mode iphost 1 tag-filter vlan-filter untag-filter discard",
            f"vlan-filter iphost 1 pri 0 vlan {service_vlan}",
        ]
    commands.append("exit")

    result = await driver.ssh.execute_config_mode(commands)

    # Update DB record
    onu.pppoe_username = username
    onu.pppoe_password = password
    if service_vlan:
        onu.service_vlan = service_vlan
    await db.flush()

    logger.info(
        "pppoe_updated_via_olt",
        onu_id=onu_db_id,
        serial=onu.serial_number,
        customer=onu.customer_id,
        pppoe_user=username,
        vlan=vlan,
    )
    return {
        "onu_id": onu_db_id,
        "serial_number": onu.serial_number,
        "pppoe_username": username,
        "service_vlan": vlan,
        "pushed_via": "OLT",
    }


async def update_wifi(
    db: AsyncSession,
    olt_id: int,
    onu_db_id: int,
    ssid_2g: str,
    ssid_5g: str,
    password: str,
) -> dict:
    onu = await get_onu_or_404(db, onu_db_id)
    if onu.olt_id != olt_id:
        raise HTTPException(status_code=404, detail="ONU not found on this OLT")

    acs = _acs_client()
    ok = await acs.configure_wifi(onu.serial_number, ssid_2g, ssid_5g, password)
    logger.info(
        "wifi_updated",
        onu_id=onu_db_id,
        serial=onu.serial_number,
        customer=onu.customer_id,
        ssid_2g=ssid_2g,
        ssid_5g=ssid_5g,
        acs_ok=ok,
    )
    return {
        "onu_id": onu_db_id,
        "serial_number": onu.serial_number,
        "ssid_2g": ssid_2g,
        "ssid_5g": ssid_5g,
        "acs_pushed": ok,
    }


async def apply_service_to_onu(
    db: AsyncSession,
    driver: BaseOLTDriver,
    onu: ONU,
    service_profile_id: int,
    vlan_override_id: int | None = None,
) -> ONUService:
    result = await db.execute(
        select(ServiceProfile).where(ServiceProfile.id == service_profile_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Service profile not found")

    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )

    if profile.tcont_id and profile.upstream_profile_id:
        await driver.configure_tcont(
            onu_ident, profile.tcont_id, profile.upstream_profile_id
        )

    if profile.gem_port and profile.tcont_id:
        await driver.configure_gemport(
            onu_ident, profile.gem_port, profile.tcont_id
        )

    vlan_id = vlan_override_id or profile.vlan_id
    sp_id_base = onu.olt_id * 10000 + onu.id * 10 + len(onu.services)
    if profile.vlan and profile.gem_port:
        await driver.create_service_port(
            sp_id_base, onu_ident, profile.vlan.vlan_tag,
            profile.gem_port, profile.service_type.value,
        )

    onu_service = ONUService(
        onu_id=onu.id,
        service_profile_id=service_profile_id,
        service_port_id=sp_id_base,
        vlan_id=vlan_id,
        status=ONUServiceStatus.ACTIVE,
    )
    db.add(onu_service)
    await db.flush()
    return onu_service


async def remove_onu(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    onu_db_id: int,
) -> None:
    olt = await get_olt_or_404(db, olt_id)
    onu = await get_onu_or_404(db, onu_db_id)
    if onu.olt_id != olt_id:
        raise HTTPException(status_code=404, detail="ONU not found on this OLT")

    driver = await driver_pool.get_driver(olt)
    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )

    for svc in onu.services:
        if svc.service_port_id:
            try:
                await driver.delete_service_port(svc.service_port_id, onu_ident)
            except Exception:
                logger.warning("service_port_delete_failed", sp_id=svc.service_port_id)

    await driver.remove_onu(onu_ident)
    await db.delete(onu)
    await db.flush()

    logger.info("onu_removed", onu_id=onu_db_id, serial=onu.serial_number)


async def set_onu_state(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    onu_db_id: int,
    new_state: AdminState,
) -> ONU:
    olt = await get_olt_or_404(db, olt_id)
    onu = await get_onu_or_404(db, onu_db_id)
    if onu.olt_id != olt_id:
        raise HTTPException(status_code=404, detail="ONU not found on this OLT")

    driver = await driver_pool.get_driver(olt)
    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )

    enabled = new_state == AdminState.ENABLED
    await driver.set_onu_admin_state(onu_ident, enabled)

    onu.admin_state = new_state
    if new_state == AdminState.SUSPENDED:
        for svc in onu.services:
            svc.status = ONUServiceStatus.SUSPENDED

    await db.flush()
    await db.refresh(onu)
    return onu


async def get_live_status(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    onu_db_id: int,
) -> dict:
    olt = await get_olt_or_404(db, olt_id)
    onu = await get_onu_or_404(db, onu_db_id)
    driver = await driver_pool.get_driver(olt)
    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )
    result = await driver.get_onu_status(onu_ident)
    return {
        "onu_id": onu.id,
        "serial_number": onu.serial_number,
        **(result.parsed or {}),
    }


def _clean_config(raw: str) -> str:
    """Strip command echo, prompt, and boilerplate from CLI output."""
    lines = []
    for l in raw.split("\n"):
        s = l.strip()
        if s and s not in ("!", "end") and "Building configuration" not in s \
                and "show running" not in s and "show gpon" not in s \
                and not s.endswith("#"):
            lines.append(s)
    return "\n".join(lines)


def _parse_interface_fields(raw: str) -> dict:
    """Extract structured fields from interface gpon-onu running config."""
    import re
    d: dict = {}
    for l in raw.split("\n"):
        s = l.strip()
        m = re.match(r"name\s+(.*)", s)
        if m:
            d["name"] = m.group(1)
        m = re.match(r"tcont\s+(\d+)\s+name\s+(\S+)\s+profile\s+(\S+)", s)
        if m:
            d["tcont_id"] = m.group(1)
            d["tcont_name"] = m.group(2)
            d["tcont_profile"] = m.group(3)
        if "gap mode" in s:
            d["tcont_gap"] = s.split("gap ")[-1]
        m = re.match(r"gemport\s+(\d+)\s+(?:name\s+(\S+)\s+)?tcont\s+(\d+)(?:\s+queue\s+(\d+))?", s)
        if m:
            d["gemport_id"] = m.group(1)
            d["gemport_name"] = m.group(2) or ""
            d["gemport_tcont"] = m.group(3)
        m = re.match(r"service-port\s+(\d+)\s+vport\s+(\d+)\s+user-vlan\s+(\d+)\s+vlan\s+(\d+)", s)
        if m:
            d["service_port_id"] = m.group(1)
            d["service_port_vport"] = m.group(2)
            d["service_port_user_vlan"] = m.group(3)
            d["service_port_vlan"] = m.group(4)
        if "switchport mode" in s:
            d["switchport_mode"] = s
    return d


def _parse_pon_onu_mng_fields(raw: str) -> dict:
    """Extract structured fields from pon-onu-mng config."""
    import re
    d: dict = {}
    for l in raw.split("\n"):
        s = l.strip()
        m = re.search(r"pppoe\s+\d+\s+nat\s+enable\s+user\s+(\S+)\s+password\s+(\S+)", s)
        if m:
            d["pppoe_username"] = m.group(1)
            d["pppoe_password"] = m.group(2)
        m = re.search(r"flow\s+(\d+)\s+pri\s+\d+\s+vlan\s+(\d+)", s)
        if m:
            d["flow_id"] = m.group(1)
            d["flow_vlan"] = m.group(2)
        if "flow mode" in s:
            d["flow_mode"] = s
        if "gemport" in s and "flow" in s:
            d["gemport_flow_binding"] = s
        if "switchport-bind" in s:
            d["switchport_bind"] = s
        if "vlan-filter-mode" in s:
            d["vlan_filter_mode"] = s
        m = re.search(r"vlan-filter\s+(?:iphost|ethuni)\s+\S+\s+pri\s+\d+\s+vlan\s+(\d+)", s)
        if m:
            d["vlan_filter_vlan"] = m.group(1)
        if "firewall" in s:
            d["firewall"] = s
        if "rx-optical-thresh" in s:
            d["rx_optical_thresh"] = s
        if "security-mgmt" in s:
            d.setdefault("security_mgmt", []).append(s)
        if "tr069-mgmt" in s:
            d.setdefault("tr069_mgmt", []).append(s)
        # Bridge mode detection
        if "onu-vlan" in s:
            d["onu_vlan"] = s
            d["mode"] = "bridge"
        if "wan-ip" in s:
            d["wan_ip_config"] = s
    if "pppoe_username" in d:
        d.setdefault("mode", "pppoe")
    elif "mode" not in d:
        d["mode"] = "unknown"
    return d


async def get_olt_config(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    onu_db_id: int,
) -> dict:
    """Retrieve comprehensive ONU details from the OLT — config, state, optical, WAN."""
    olt = await get_olt_or_404(db, olt_id)
    onu = await get_onu_or_404(db, onu_db_id)
    driver = await driver_pool.get_driver(olt)

    path_prefix = "gpon-onu_" if olt.platform.value == "ZXAN" else "gpon_onu-"
    onu_path = f"{path_prefix}{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}"
    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )

    result: dict = {
        "onu_id": onu.id,
        "serial_number": onu.serial_number,
        "onu_path": onu_path,
    }

    # 1. Interface running config (tcont, gemport, service-port)
    # Uses 'show running-config interface gpon-onu_F/S/P:ID' — fails silently for offline ONUs
    try:
        raw = await driver.ssh.execute(f"show running-config interface {onu_path}")
        result["interface_config"] = _clean_config(raw)
        result["interface"] = _parse_interface_fields(raw)
    except Exception:
        result["interface_config"] = ""
        result["interface"] = {}

    # 2. pon-onu-mng config (flow, PPPoE, vlan-filter, security)
    # Uses 'show onu running config gpon-onu_F/S/P:ID'
    try:
        raw = await driver.ssh.execute(f"show onu running config {onu_path}")
        result["pon_onu_mng_config"] = _clean_config(raw)
        result["pon_onu_mng"] = _parse_pon_onu_mng_fields(raw)
    except Exception:
        result["pon_onu_mng_config"] = ""
        result["pon_onu_mng"] = {}


    # 3. ONU detail info (state, distance, online duration)
    try:
        status_result = await driver.get_onu_status(onu_ident)
        result["status"] = status_result.parsed or {}
    except Exception:
        result["status"] = {}

    # 4. Optical info (Rx/Tx power)
    try:
        raw = await driver.ssh.execute(
            f"show gpon onu optical-info {onu_path}"
        )
        result["optical"] = self_parse_optical(raw)
    except Exception:
        result["optical"] = {}

    # 5. WAN / IP host
    try:
        wan_result = await driver.get_onu_wan_info(onu_ident)
        result["wan"] = wan_result.parsed or {}
    except Exception:
        result["wan"] = {}

    return result


def self_parse_optical(raw: str) -> dict:
    """Parse optical info output."""
    import re
    d = {}
    patterns = {
        "rx_power": re.compile(r"Rx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.I),
        "tx_power": re.compile(r"Tx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.I),
        "olt_rx_power": re.compile(r"OLT\s+Rx\s+(?:optical\s+)?power\s*[:\(]\s*([-\d.]+)", re.I),
        "temperature": re.compile(r"[Tt]emperature\s*[:\(]\s*([-\d.]+)", re.I),
        "voltage": re.compile(r"[Vv]oltage\s*[:\(]\s*([-\d.]+)", re.I),
    }
    for key, pattern in patterns.items():
        m = pattern.search(raw)
        if m:
            d[key] = m.group(1)
    return d


async def get_wan_info(
    db: AsyncSession,
    driver_pool: OLTDriverPool,
    olt_id: int,
    onu_db_id: int,
) -> dict:
    """Query ONU WAN port status and IP assignment from the OLT."""
    olt = await get_olt_or_404(db, olt_id)
    onu = await get_onu_or_404(db, onu_db_id)
    driver = await driver_pool.get_driver(olt)
    onu_ident = ONUIdentifier(
        frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
    )
    result = await driver.get_onu_wan_info(onu_ident)
    return {
        "onu_id": onu.id,
        "serial_number": onu.serial_number,
        **(result.parsed or {}),
    }
