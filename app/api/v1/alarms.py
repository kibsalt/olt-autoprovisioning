from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.alarm import AlarmStatus, TicketStatus
from app.schemas.alarm import (
    AlarmResponse, TechnicianCreate, TechnicianResponse, TechnicianUpdate,
    TicketAssign, TicketResponse, TicketResolve,
)
from app.schemas.common import APIResponse
from app.services import alarm_service

router = APIRouter()


def _fmt_alarm(a) -> dict:
    onu = a.onu
    return AlarmResponse(
        id=a.id,
        onu_id=a.onu_id,
        serial_number=onu.serial_number if onu else "?",
        customer_id=onu.customer_id if onu else "?",
        olt_name=onu.olt.name if (onu and onu.olt) else "?",
        port=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}" if onu else "?",
        alarm_type=a.alarm_type,
        severity=a.severity,
        status=a.status,
        rx_power=a.rx_power,
        detected_at=a.detected_at,
        resolved_at=a.resolved_at,
        notes=a.notes,
        ticket_id=a.ticket.id if a.ticket else None,
    )


def _fmt_ticket(t) -> dict:
    onu = t.onu
    return TicketResponse(
        id=t.id,
        alarm_id=t.alarm_id,
        onu_id=t.onu_id,
        serial_number=onu.serial_number if onu else "?",
        customer_id=t.customer_id,
        olt_name=onu.olt.name if (onu and onu.olt) else "?",
        port=f"{onu.frame}/{onu.slot}/{onu.port}:{onu.onu_id}" if onu else "?",
        title=t.title,
        description=t.description,
        status=t.status,
        priority=t.priority,
        assigned_to=t.assigned_to,
        technician_name=t.technician.name if t.technician else None,
        assigned_at=t.assigned_at,
        resolved_at=t.resolved_at,
        resolution_notes=t.resolution_notes,
        created_at=t.created_at,
    )


# ── Alarms ────────────────────────────────────────────────────────────────────

@router.get("/alarms", response_model=APIResponse[list[AlarmResponse]])
async def list_alarms(
    status: AlarmStatus | None = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    alarms = await alarm_service.list_alarms(db, status=status, limit=limit)
    return APIResponse(success=True, data=[_fmt_alarm(a) for a in alarms])


# ── Tickets ───────────────────────────────────────────────────────────────────

@router.get("/tickets", response_model=APIResponse[list[TicketResponse]])
async def list_tickets(
    status: TicketStatus | None = Query(None),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    tickets = await alarm_service.list_tickets(db, status=status, limit=limit)
    return APIResponse(success=True, data=[_fmt_ticket(t) for t in tickets])


@router.post("/tickets/{ticket_id}/assign", response_model=APIResponse[TicketResponse])
async def assign_ticket(
    ticket_id: int,
    data: TicketAssign,
    db: AsyncSession = Depends(get_db),
):
    ticket = await alarm_service.assign_ticket(db, ticket_id, data.technician_id, data.notes)
    await db.commit()
    return APIResponse(success=True, data=_fmt_ticket(ticket))


@router.post("/tickets/{ticket_id}/resolve", response_model=APIResponse[TicketResponse])
async def resolve_ticket(
    ticket_id: int,
    data: TicketResolve,
    db: AsyncSession = Depends(get_db),
):
    ticket = await alarm_service.resolve_ticket(db, ticket_id, data.resolution_notes)
    await db.commit()
    return APIResponse(success=True, data=_fmt_ticket(ticket))


# ── Technicians ───────────────────────────────────────────────────────────────

@router.get("/technicians", response_model=APIResponse[list[TechnicianResponse]])
async def list_technicians(db: AsyncSession = Depends(get_db)):
    techs = await alarm_service.list_technicians(db)
    return APIResponse(success=True, data=[TechnicianResponse.model_validate(t) for t in techs])


@router.post("/technicians", response_model=APIResponse[TechnicianResponse], status_code=201)
async def create_technician(data: TechnicianCreate, db: AsyncSession = Depends(get_db)):
    tech = await alarm_service.create_technician(db, data)
    await db.commit()
    return APIResponse(success=True, data=TechnicianResponse.model_validate(tech))


@router.put("/technicians/{tech_id}", response_model=APIResponse[TechnicianResponse])
async def update_technician(tech_id: int, data: TechnicianUpdate, db: AsyncSession = Depends(get_db)):
    tech = await alarm_service.update_technician(db, tech_id, data)
    await db.commit()
    return APIResponse(success=True, data=TechnicianResponse.model_validate(tech))


@router.delete("/technicians/{tech_id}", status_code=204)
async def delete_technician(tech_id: int, db: AsyncSession = Depends(get_db)):
    await alarm_service.delete_technician(db, tech_id)
    await db.commit()
