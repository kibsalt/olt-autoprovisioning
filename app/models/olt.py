from enum import Enum as PyEnum

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OLTModel(str, PyEnum):
    C300 = "C300"
    C320 = "C320"
    C600 = "C600"
    C620 = "C620"
    C650 = "C650"
    HSGQ2 = "HSGQ-2"
    OTHERS = "Others"


class OLTPlatform(str, PyEnum):
    ZXAN = "ZXAN"
    TITAN = "TITAN"


MODEL_TO_PLATFORM = {
    OLTModel.C300: OLTPlatform.ZXAN,
    OLTModel.C320: OLTPlatform.ZXAN,
    OLTModel.C600: OLTPlatform.TITAN,
    OLTModel.C620: OLTPlatform.TITAN,
    OLTModel.C650: OLTPlatform.TITAN,
    OLTModel.HSGQ2: OLTPlatform.ZXAN,
    OLTModel.OTHERS: OLTPlatform.ZXAN,
}


class OLTStatus(str, PyEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


class OLT(Base, TimestampMixin):
    __tablename__ = "olts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    host: Mapped[str] = mapped_column(String(45), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=23)  # Telnet port
    model: Mapped[OLTModel] = mapped_column(
        Enum(OLTModel, values_callable=lambda obj: [e.value for e in obj]), nullable=False
    )
    platform: Mapped[OLTPlatform] = mapped_column(
        Enum(OLTPlatform), nullable=False
    )
    software_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ssh_username: Mapped[str] = mapped_column(String(256), nullable=False)
    ssh_password: Mapped[str] = mapped_column(String(512), nullable=False)
    enable_password: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[OLTStatus] = mapped_column(
        Enum(OLTStatus), nullable=False, default=OLTStatus.ACTIVE
    )

    onus: Mapped[list["ONU"]] = relationship(back_populates="olt", lazy="selectin")

    def __repr__(self) -> str:
        return f"<OLT {self.name} ({self.model.value})>"
