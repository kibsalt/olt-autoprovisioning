"""Unified notification dispatch for ONU provisioning."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationStatus, NotificationType
from app.models.onu import ONU
from app.notifications.email_service import send_wifi_credentials_email
from app.notifications.sms_service import send_wifi_credentials_sms
from app.notifications.whatsapp_service import send_wifi_credentials_whatsapp

logger = structlog.get_logger()


async def notify_customer_wifi_credentials(db: AsyncSession, onu: ONU) -> None:
    """Send WiFi credentials to customer via available channels."""
    if not onu.wifi_ssid_2g or not onu.wifi_password:
        return

    # Send email if available
    if onu.customer_email:
        success = await send_wifi_credentials_email(
            to_email=onu.customer_email,
            customer_id=onu.customer_id,
            ssid_2g=onu.wifi_ssid_2g,
            ssid_5g=onu.wifi_ssid_5g or "",
            password=onu.wifi_password,
        )
        notification = Notification(
            onu_id=onu.id,
            customer_id=onu.customer_id,
            notification_type=NotificationType.EMAIL,
            recipient=onu.customer_email,
            status=NotificationStatus.SENT if success else NotificationStatus.FAILED,
        )
        db.add(notification)

    # Send SMS if available
    if onu.customer_phone:
        success = await send_wifi_credentials_sms(
            phone_number=onu.customer_phone,
            customer_id=onu.customer_id,
            ssid_2g=onu.wifi_ssid_2g,
            ssid_5g=onu.wifi_ssid_5g or "",
            password=onu.wifi_password,
        )
        notification = Notification(
            onu_id=onu.id,
            customer_id=onu.customer_id,
            notification_type=NotificationType.SMS,
            recipient=onu.customer_phone,
            status=NotificationStatus.SENT if success else NotificationStatus.FAILED,
        )
        db.add(notification)

    # Send WhatsApp if phone is available
    if onu.customer_phone:
        success = await send_wifi_credentials_whatsapp(
            phone_number=onu.customer_phone,
            customer_name=onu.customer_name or onu.customer_id,
            ssid_2g=onu.wifi_ssid_2g,
            ssid_5g=onu.wifi_ssid_5g or "",
            password=onu.wifi_password,
        )
        if success:
            notification = Notification(
                onu_id=onu.id,
                customer_id=onu.customer_id,
                notification_type=NotificationType.WHATSAPP,
                recipient=onu.customer_phone,
                status=NotificationStatus.SENT,
            )
            db.add(notification)

    await db.flush()
