import aiosmtplib
import structlog
from email.message import EmailMessage

from app.config import settings

logger = structlog.get_logger()


async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a generic email."""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_use_tls,
        )
        logger.info("email_sent", to=to_email, subject=subject)
        return True
    except Exception:
        logger.exception("email_failed", to=to_email)
        return False


async def send_wifi_credentials_email(
    to_email: str,
    customer_id: str,
    ssid_2g: str,
    ssid_5g: str,
    password: str,
) -> bool:
    """Send WiFi credentials to customer via email."""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg["Subject"] = "Your JTL Internet - WiFi Credentials"

    body = f"""Dear Customer ({customer_id}),

Welcome to JTL Internet! Your WiFi connection is now active.

Your WiFi Credentials:

  2.4GHz Network:
    SSID: {ssid_2g}
    Password: {password}

  5GHz Network:
    SSID: {ssid_5g}
    Password: {password}

For better performance, connect to the 5GHz network when you are close to the router.

If you need assistance, please contact our support team.

Thank you for choosing JTL!
"""
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_use_tls,
        )
        logger.info("wifi_email_sent", to=to_email, customer=customer_id)
        return True
    except Exception:
        logger.exception("wifi_email_failed", to=to_email, customer=customer_id)
        return False
