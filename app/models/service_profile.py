from enum import Enum as PyEnum

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ServiceType(str, PyEnum):
    INTERNET = "internet"
    VOIP = "voip"
    IPTV = "iptv"


class ServiceProfile(Base, TimestampMixin):
    __tablename__ = "service_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    service_type: Mapped[ServiceType] = mapped_column(
        Enum(ServiceType), nullable=False
    )
    upstream_profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bandwidth_profiles.id"), nullable=True
    )
    downstream_profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bandwidth_profiles.id"), nullable=True
    )
    vlan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("vlans.id"), nullable=True
    )
    gem_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tcont_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    upstream_profile: Mapped["BandwidthProfile | None"] = relationship(
        foreign_keys=[upstream_profile_id], lazy="selectin"
    )
    downstream_profile: Mapped["BandwidthProfile | None"] = relationship(
        foreign_keys=[downstream_profile_id], lazy="selectin"
    )
    vlan: Mapped["VLAN | None"] = relationship(lazy="selectin")

    def __repr__(self) -> str:
        return f"<ServiceProfile {self.name}>"
