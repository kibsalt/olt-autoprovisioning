from datetime import datetime

from pydantic import BaseModel, Field

from app.models.alarm import AlarmSeverity, AlarmStatus, AlarmType, TicketPriority, TicketStatus


# ── Technician ────────────────────────────────────────────────────────────────

class TechnicianCreate(BaseModel):
    name:  str
    phone: str | None = None
    email: str | None = None
    zone:  str | None = None


class TechnicianUpdate(BaseModel):
    name:   str | None = None
    phone:  str | None = None
    email:  str | None = None
    zone:   str | None = None
    active: bool | None = None


class TechnicianResponse(BaseModel):
    id:         int
    name:       str
    phone:      str | None
    email:      str | None
    zone:       str | None
    active:     bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Alarm ─────────────────────────────────────────────────────────────────────

class AlarmResponse(BaseModel):
    id:           int
    onu_id:       int
    serial_number: str
    customer_id:  str
    olt_name:     str
    port:         str   # "frame/slot/port:onu_id"
    alarm_type:   AlarmType
    severity:     AlarmSeverity
    status:       AlarmStatus
    rx_power:     float | None
    detected_at:  datetime
    resolved_at:  datetime | None
    notes:        str | None
    ticket_id:    int | None

    model_config = {"from_attributes": True}


# ── Ticket ────────────────────────────────────────────────────────────────────

class TicketResponse(BaseModel):
    id:               int
    alarm_id:         int | None
    onu_id:           int
    serial_number:    str
    customer_id:      str
    olt_name:         str
    port:             str
    title:            str
    description:      str | None
    status:           TicketStatus
    priority:         TicketPriority
    assigned_to:      int | None
    technician_name:  str | None
    assigned_at:      datetime | None
    resolved_at:      datetime | None
    resolution_notes: str | None
    created_at:       datetime

    model_config = {"from_attributes": True}


class TicketAssign(BaseModel):
    technician_id: int
    notes: str | None = None


class TicketResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=1)
