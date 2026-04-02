from enum import Enum as PyEnum

from sqlalchemy import Enum, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class AdminState(str, PyEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    SUSPENDED = "suspended"


class OperState(str, PyEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


class ONUServiceStatus(str, PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"
    FAILED = "failed"


class ONU(Base, TimestampMixin):
    __tablename__ = "onus"
    __table_args__ = (
        UniqueConstraint("olt_id", "frame", "slot", "port", "onu_id", name="uq_onu_location"),
        UniqueConstraint("serial_number", name="uq_serial_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    olt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("olts.id"), nullable=False, index=True
    )
    serial_number: Mapped[str] = mapped_column(String(16), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    frame: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    slot: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    port: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    onu_id: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    onu_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    admin_state: Mapped[AdminState] = mapped_column(
        Enum(AdminState), nullable=False, default=AdminState.ENABLED
    )
    oper_state: Mapped[OperState] = mapped_column(
        Enum(OperState), nullable=False, default=OperState.UNKNOWN
    )
    customer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    wifi_ssid_2g: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wifi_ssid_5g: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wifi_password: Mapped[str | None] = mapped_column(String(64), nullable=True)
    package_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    service_vlan: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    oam_vlan: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    svlan: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    pppoe_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pppoe_password: Mapped[str | None] = mapped_column(String(64), nullable=True)

    olt: Mapped["OLT"] = relationship(back_populates="onus")
    services: Mapped[list["ONUService"]] = relationship(
        back_populates="onu", lazy="selectin", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ONU {self.serial_number} on {self.frame}/{self.slot}/{self.port}:{self.onu_id}>"


class ONUService(Base, TimestampMixin):
    __tablename__ = "onu_services"
    __table_args__ = (
        UniqueConstraint("onu_id", "service_profile_id", name="uq_onu_service"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("onus.id"), nullable=False, index=True
    )
    service_profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("service_profiles.id"), nullable=False
    )
    service_port_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vlan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("vlans.id"), nullable=True
    )
    status: Mapped[ONUServiceStatus] = mapped_column(
        Enum(ONUServiceStatus), nullable=False, default=ONUServiceStatus.PENDING
    )

    onu: Mapped["ONU"] = relationship(back_populates="services")
    service_profile: Mapped["ServiceProfile"] = relationship(lazy="selectin")
    vlan: Mapped["VLAN | None"] = relationship(lazy="selectin")
