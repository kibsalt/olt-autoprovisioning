import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AlarmType(str, enum.Enum):
    LOS    = "los"     # Loss of Signal — ONU offline
    LOW_RX = "low_rx"  # Rx optical power below threshold


class AlarmSeverity(str, enum.Enum):
    CRITICAL = "critical"  # LOS or Rx < -28 dBm
    MAJOR    = "major"     # Rx < -27 dBm
    MINOR    = "minor"     # Rx < -26 dBm (warning)


class AlarmStatus(str, enum.Enum):
    ACTIVE   = "active"
    RESOLVED = "resolved"


class TicketStatus(str, enum.Enum):
    OPEN        = "open"
    ASSIGNED    = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED    = "resolved"
    CLOSED      = "closed"


class TicketPriority(str, enum.Enum):
    HIGH   = "high"
    MEDIUM = "medium"
    LOW    = "low"


class Technician(Base, TimestampMixin):
    __tablename__ = "technicians"

    id:    Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:  Mapped[str]      = mapped_column(String(255), nullable=False)
    phone: Mapped[str|None] = mapped_column(String(30),  nullable=True)
    email: Mapped[str|None] = mapped_column(String(255), nullable=True)
    zone:  Mapped[str|None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool]    = mapped_column(Boolean, default=True, nullable=False)

    tickets: Mapped[list["Ticket"]] = relationship("Ticket", back_populates="technician")


class Alarm(Base, TimestampMixin):
    __tablename__ = "alarms"

    id:          Mapped[int]         = mapped_column(Integer, primary_key=True, autoincrement=True)
    onu_id:      Mapped[int]         = mapped_column(Integer, ForeignKey("onus.id", ondelete="CASCADE"), nullable=False)
    alarm_type:  Mapped[AlarmType]   = mapped_column(Enum(AlarmType,   values_callable=lambda x: [e.value for e in x]), nullable=False)
    severity:    Mapped[AlarmSeverity] = mapped_column(Enum(AlarmSeverity, values_callable=lambda x: [e.value for e in x]), nullable=False)
    status:      Mapped[AlarmStatus] = mapped_column(Enum(AlarmStatus,  values_callable=lambda x: [e.value for e in x]), nullable=False, default=AlarmStatus.ACTIVE)
    rx_power:    Mapped[float|None]  = mapped_column(Float,   nullable=True)
    detected_at: Mapped[datetime]    = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    notes:       Mapped[str|None]    = mapped_column(Text, nullable=True)

    onu:    Mapped["ONU"]          = relationship("ONU")
    ticket: Mapped["Ticket|None"]  = relationship("Ticket", back_populates="alarm", uselist=False)


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    alarm_id:         Mapped[int|None]       = mapped_column(Integer, ForeignKey("alarms.id", ondelete="SET NULL"), nullable=True)
    onu_id:           Mapped[int]            = mapped_column(Integer, ForeignKey("onus.id", ondelete="CASCADE"), nullable=False)
    customer_id:      Mapped[str]            = mapped_column(String(255), nullable=False)
    title:            Mapped[str]            = mapped_column(String(500), nullable=False)
    description:      Mapped[str|None]       = mapped_column(Text, nullable=True)
    status:           Mapped[TicketStatus]   = mapped_column(Enum(TicketStatus,   values_callable=lambda x: [e.value for e in x]), nullable=False, default=TicketStatus.OPEN)
    priority:         Mapped[TicketPriority] = mapped_column(Enum(TicketPriority, values_callable=lambda x: [e.value for e in x]), nullable=False, default=TicketPriority.HIGH)
    assigned_to:      Mapped[int|None]       = mapped_column(Integer, ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True)
    assigned_at:      Mapped[datetime|None]  = mapped_column(DateTime, nullable=True)
    resolved_at:      Mapped[datetime|None]  = mapped_column(DateTime, nullable=True)
    resolution_notes: Mapped[str|None]       = mapped_column(Text, nullable=True)

    alarm:      Mapped["Alarm|None"]      = relationship("Alarm", back_populates="ticket")
    onu:        Mapped["ONU"]             = relationship("ONU")
    technician: Mapped["Technician|None"] = relationship("Technician", back_populates="tickets")
