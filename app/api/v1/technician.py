"""Technician-facing endpoints — JWT + technician or admin role required."""
import secrets
import string
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_db, require_technician
from app.models.alarm import Alarm, AlarmStatus, AlarmType, Ticket, TicketStatus
from app.models.customer import FixedPppoeCust
from app.models.olt import OLT, OLTStatus
from app.models.onu import ONU
from app.models.user import User, UserRole
from app.olt_driver.base import ONUIdentifier
from app.services.provision_service import bss_provision
from app.schemas.provision import ProvisionRequest

logger = structlog.get_logger()

router = APIRouter(prefix="/tech", tags=["Technician"])

_ALPHANUM = string.ascii_letters + string.digits


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _random_password(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHANUM) for _ in range(length))


# ── Request / Response schemas ────────────────────────────────────────────────

class TicketOut(BaseModel):
    id: int
    title: str
    description: str | None
    status: str
    priority: str
    customer_id: str
    assigned_to: int | None
    assigned_at: datetime | None
    resolved_at: datetime | None
    acknowledged_at: datetime | None
    acknowledge_notes: str | None
    resolution_notes: str | None
    created_at: datetime
    alarm_type: str | None
    onu_serial: str | None

    model_config = {"from_attributes": True}


class AcknowledgeRequest(BaseModel):
    notes: str


class CloseRequest(BaseModel):
    notes: str


class ProvisionTechRequest(BaseModel):
    olt_id: int
    serial_number: str
    onu_type: str
    customer_id: str
    frame: int
    slot: int
    port: int


class ProvisionTechResponse(BaseModel):
    success: bool
    customer_id: str
    full_name: str
    serial_number: str
    olt_name: str
    onu_location: str
    wifi_ssid_2g: str
    wifi_ssid_5g: str
    wifi_password: str
    pppoe_username: str
    vlan_id: int


class OLTOut(BaseModel):
    id: int
    name: str
    host: str
    model: str


class UnregisteredONU(BaseModel):
    frame: int
    slot: int
    port: int
    serial_number: str
    onu_type: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ticket_out(ticket: Ticket) -> dict:
    alarm_type = None
    if ticket.alarm:
        alarm_type = ticket.alarm.alarm_type.value
    onu_serial = None
    if ticket.onu:
        onu_serial = ticket.onu.serial_number
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "customer_id": ticket.customer_id,
        "assigned_to": ticket.assigned_to,
        "assigned_at": ticket.assigned_at,
        "resolved_at": ticket.resolved_at,
        "acknowledged_at": ticket.acknowledged_at,
        "acknowledge_notes": ticket.acknowledge_notes,
        "resolution_notes": ticket.resolution_notes,
        "created_at": ticket.created_at,
        "alarm_type": alarm_type,
        "onu_serial": onu_serial,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tickets", response_model=list[TicketOut])
async def list_my_tickets(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """
    For technicians: returns tickets assigned to their Technician record.
    For admins: returns all unassigned + assigned tickets.
    """
    q = (
        select(Ticket)
        .options(
            selectinload(Ticket.alarm),
            selectinload(Ticket.onu),
            selectinload(Ticket.technician),
        )
        .order_by(Ticket.created_at.desc())
    )

    if current_user.role == UserRole.ADMIN:
        q = q.where(
            Ticket.status.in_([
                TicketStatus.OPEN,
                TicketStatus.ASSIGNED,
                TicketStatus.IN_PROGRESS,
                TicketStatus.ACKNOWLEDGED,
            ])
        )
    else:
        if not current_user.technician_id:
            return []
        q = q.where(Ticket.assigned_to == current_user.technician_id)

    result = await db.execute(q)
    tickets = result.scalars().all()
    return [_ticket_out(t) for t in tickets]


@router.post("/tickets/{ticket_id}/acknowledge", response_model=TicketOut)
async def acknowledge_ticket(
    ticket_id: int,
    body: AcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """Acknowledge a ticket — set status to ACKNOWLEDGED."""
    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.alarm), selectinload(Ticket.onu))
        .where(Ticket.id == ticket_id)
    )
    ticket: Ticket | None = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Technicians can only acknowledge their own assigned tickets
    if current_user.role == UserRole.TECHNICIAN:
        if ticket.assigned_to != current_user.technician_id:
            raise HTTPException(status_code=403, detail="Ticket is not assigned to you")

    if ticket.status not in (TicketStatus.OPEN, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot acknowledge ticket in status '{ticket.status.value}'",
        )

    now = _now()
    ticket.status = TicketStatus.ACKNOWLEDGED
    ticket.acknowledged_at = now
    ticket.acknowledge_notes = body.notes
    await db.flush()

    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.alarm), selectinload(Ticket.onu))
        .where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one()
    return _ticket_out(ticket)


@router.post("/tickets/{ticket_id}/close", response_model=TicketOut)
async def close_ticket(
    ticket_id: int,
    body: CloseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_technician),
):
    """
    Close a ticket after verifying live ONU recovery via OLT SSH.
    - LOS ticket: ONU oper_state must be 'working'
    - LOW_RX ticket: rx_power must be > -26.0 dBm
    """
    result = await db.execute(
        select(Ticket)
        .options(
            selectinload(Ticket.alarm),
            selectinload(Ticket.onu).selectinload(ONU.olt),
        )
        .where(Ticket.id == ticket_id)
    )
    ticket: Ticket | None = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Technicians can only close their own assigned tickets
    if current_user.role == UserRole.TECHNICIAN:
        if ticket.assigned_to != current_user.technician_id:
            raise HTTPException(status_code=403, detail="Ticket is not assigned to you")

    if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise HTTPException(
            status_code=409,
            detail=f"Ticket is already '{ticket.status.value}'",
        )

    # Check live ONU status via OLT driver if ONU is linked
    if ticket.onu and ticket.alarm:
        onu = ticket.onu
        olt = onu.olt
        driver_pool = request.app.state.driver_pool

        try:
            driver = await driver_pool.get_driver(olt)
            onu_ident = ONUIdentifier(
                frame=onu.frame, slot=onu.slot, port=onu.port, onu_id=onu.onu_id
            )

            if ticket.alarm.alarm_type == AlarmType.LOS:
                # Check oper_state via get_onu_status
                cmd_result = await driver.get_onu_status(onu_ident)
                parsed = cmd_result.parsed or {}
                oper_state = str(parsed.get("oper_state", "")).lower()
                if "working" not in oper_state and "online" not in oper_state:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"ONU not yet recovered: oper_state='{oper_state}'",
                    )

            elif ticket.alarm.alarm_type == AlarmType.LOW_RX:
                # Check current Rx power
                rx_map = await driver.get_port_onu_rx(
                    onu.frame, onu.slot, onu.port, onu_ids=[onu.onu_id]
                )
                rx_power = rx_map.get(onu.onu_id)
                if rx_power is None:
                    # Fallback: try optical info
                    optical = await driver.get_onu_optical(onu_ident)
                    rx_raw = optical.get("rx_power")
                    rx_power = float(rx_raw) if rx_raw is not None else None

                if rx_power is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Unable to read ONU Rx power — cannot confirm recovery",
                    )
                if rx_power <= -26.0:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"ONU not yet recovered: rx_power={rx_power:.2f} dBm (threshold: -26.0 dBm)",
                    )

        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("close_ticket_olt_check_failed", ticket_id=ticket_id, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"OLT communication error during recovery check: {exc}",
            )

    # All checks passed — close ticket
    now = _now()
    ticket.status = TicketStatus.CLOSED
    ticket.resolved_at = now
    ticket.resolution_notes = body.notes

    # Also resolve the alarm
    if ticket.alarm and ticket.alarm.status == AlarmStatus.ACTIVE:
        ticket.alarm.status = AlarmStatus.RESOLVED
        ticket.alarm.resolved_at = now
        ticket.alarm.notes = f"Closed by technician: {body.notes}"

    await db.flush()

    result = await db.execute(
        select(Ticket)
        .options(selectinload(Ticket.alarm), selectinload(Ticket.onu))
        .where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one()
    return _ticket_out(ticket)


@router.get("/olts", response_model=list[OLTOut])
async def list_olts(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_technician),
):
    """List all active OLTs."""
    result = await db.execute(
        select(OLT)
        .where(OLT.status == OLTStatus.ACTIVE)
        .order_by(OLT.name)
    )
    olts = result.scalars().all()
    return [
        {"id": o.id, "name": o.name, "host": o.host, "model": o.model.value}
        for o in olts
    ]


@router.get("/olts/{olt_id}/unregistered", response_model=list[UnregisteredONU])
async def list_unregistered(
    olt_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_technician),
):
    """Discover unregistered ONUs across ports 1/9/1 through 1/9/8 on an OLT."""
    result = await db.execute(select(OLT).where(OLT.id == olt_id))
    olt: OLT | None = result.scalar_one_or_none()
    if not olt:
        raise HTTPException(status_code=404, detail="OLT not found")

    driver_pool = request.app.state.driver_pool
    try:
        driver = await driver_pool.get_driver(olt)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to OLT: {exc}",
        )

    unregistered: list[dict] = []
    for port in range(1, 9):  # ports 1-8
        try:
            onus = await driver.discover_unregistered_onus(1, 9, port)
            for onu in onus:
                unregistered.append(
                    {
                        "frame": 1,
                        "slot": 9,
                        "port": port,
                        "serial_number": onu.get("serial_number", ""),
                        "onu_type": onu.get("onu_type") or onu.get("type"),
                    }
                )
        except Exception as exc:
            logger.warning(
                "unregistered_scan_port_failed",
                olt_id=olt_id,
                port=f"1/9/{port}",
                error=str(exc),
            )
    return unregistered


@router.post("/provision", response_model=ProvisionTechResponse)
async def tech_provision(
    body: ProvisionTechRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_technician),
):
    """
    Provision an ONU using customer data from fixed_pppoe_cust.
    Returns WiFi credentials auto-generated for the customer.
    """
    # 1. Lookup customer
    result = await db.execute(
        select(FixedPppoeCust).where(FixedPppoeCust.customer_id == body.customer_id)
    )
    customer: FixedPppoeCust | None = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=404,
            detail=f"Customer '{body.customer_id}' not found in provisioning database",
        )

    # 2. Check if customer_id already bound to an ONU
    existing_onu = await db.execute(
        select(ONU).where(ONU.customer_id == body.customer_id)
    )
    if existing_onu.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail=f"Customer '{body.customer_id}' is already provisioned with an ONU",
        )

    # 3. Lookup OLT by id
    olt_result = await db.execute(select(OLT).where(OLT.id == body.olt_id))
    olt: OLT | None = olt_result.scalar_one_or_none()
    if not olt:
        raise HTTPException(status_code=404, detail=f"OLT id={body.olt_id} not found")

    # 4. Generate WiFi credentials per spec: ssid_2g = JTL_{customer_id}_2G
    wifi_ssid_2g = f"JTL_{body.customer_id}_2G"
    wifi_ssid_5g = f"JTL_{body.customer_id}_5G"
    wifi_password = _random_password(8)

    # 5. Build ProvisionRequest for the existing provision_service
    prov_req = ProvisionRequest(
        customer_id=body.customer_id,
        customer_name=customer.full_name,
        onu_serial_number=body.serial_number,
        onu_model=body.onu_type,
        olt_id=olt.name,
        package_id=customer.service_id,
        service_vlan=customer.vlan_id,
        oam_vlan=1450,
        pppoe_username=customer.pppoe_username,
        pppoe_password=customer.pppoe_password,
        description=f"Customer:{body.customer_id}",
    )

    driver_pool = request.app.state.driver_pool
    try:
        prov_result = await bss_provision(db, driver_pool, prov_req)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("tech_provision_failed", customer_id=body.customer_id, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Provisioning failed: {exc}",
        )

    # Update WiFi in ONU record to match our spec-defined naming
    onu_result = await db.execute(
        select(ONU).where(ONU.customer_id == body.customer_id)
    )
    onu_record = onu_result.scalar_one_or_none()
    if onu_record:
        onu_record.wifi_ssid_2g = wifi_ssid_2g
        onu_record.wifi_ssid_5g = wifi_ssid_5g
        onu_record.wifi_password = wifi_password
        await db.flush()

    return ProvisionTechResponse(
        success=True,
        customer_id=body.customer_id,
        full_name=customer.full_name,
        serial_number=body.serial_number,
        olt_name=olt.name,
        onu_location=prov_result.onu_location,
        wifi_ssid_2g=wifi_ssid_2g,
        wifi_ssid_5g=wifi_ssid_5g,
        wifi_password=wifi_password,
        pppoe_username=customer.pppoe_username,
        vlan_id=customer.vlan_id,
    )
