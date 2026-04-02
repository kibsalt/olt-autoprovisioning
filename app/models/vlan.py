from enum import Enum as PyEnum

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class VLANServiceType(str, PyEnum):
    INTERNET = "internet"
    VOIP = "voip"
    IPTV = "iptv"
    MANAGEMENT = "management"


class VLAN(Base, TimestampMixin):
    __tablename__ = "vlans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vlan_tag: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    service_type: Mapped[VLANServiceType] = mapped_column(
        Enum(VLANServiceType), nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    def __repr__(self) -> str:
        return f"<VLAN {self.vlan_tag} ({self.name})>"
