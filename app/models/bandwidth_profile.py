from enum import Enum as PyEnum

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DBAType(str, PyEnum):
    TYPE1 = "type1"
    TYPE2 = "type2"
    TYPE3 = "type3"
    TYPE4 = "type4"
    TYPE5 = "type5"


class Direction(str, PyEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"


class BandwidthProfile(Base, TimestampMixin):
    __tablename__ = "bandwidth_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    traffic_table_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cir: Mapped[int] = mapped_column(Integer, nullable=False)
    pir: Mapped[int] = mapped_column(Integer, nullable=False)
    cbs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pbs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dba_type: Mapped[DBAType] = mapped_column(
        Enum(DBAType), nullable=False, default=DBAType.TYPE3
    )
    direction: Mapped[Direction] = mapped_column(Enum(Direction), nullable=False)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)

    def __repr__(self) -> str:
        return f"<BandwidthProfile {self.name} ({self.direction.value})>"
