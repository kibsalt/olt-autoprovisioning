from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NotificationType(str, PyEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class NotificationStatus(str, PyEnum):
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    onu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("onus.id"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType), nullable=False
    )
    recipient: Mapped[str] = mapped_column(String(256), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus), nullable=False, default=NotificationStatus.PENDING
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
