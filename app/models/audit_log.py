from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), index=True
    )
    api_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    olt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("olts.id"), nullable=True, index=True
    )
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    olt_commands: Mapped[list | None] = mapped_column(JSON, nullable=True)
    olt_responses: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
