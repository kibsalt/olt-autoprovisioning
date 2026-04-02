import africastalking
import structlog

from app.config import settings

logger = structlog.get_logger()

_initialized = False


def _init_at():
    global _initialized
    if not _initialized and settings.at_username and settings.at_api_key:
        africastalking.initialize(settings.at_username, settings.at_api_key)
        _initialized = True


async def send_sms(phone_number: str, message: str) -> bool:
    """Send a generic SMS message via Africa's Talking."""
    _init_at()
    if not _initialized:
        logger.warning("sms_not_configured")
        return False
    try:
        sms = africastalking.SMS
        response = sms.send(
            message,
            [phone_number],
            sender_id=settings.at_sender_id if settings.at_sender_id else None,
        )
        logger.info("sms_sent", phone=phone_number, response=str(response))
        return True
    except Exception:
        logger.exception("sms_failed", phone=phone_number)
        return False


async def send_wifi_credentials_sms(
    phone_number: str,
    customer_id: str,
    ssid_2g: str,
    ssid_5g: str,
    password: str,
) -> bool:
    """Send WiFi credentials to customer via SMS using Africa's Talking."""
    _init_at()

    message = (
        f"JTL Internet - WiFi Credentials\n"
        f"2.4GHz: {ssid_2g}\n"
        f"5GHz: {ssid_5g}\n"
        f"Password: {password}\n"
        f"Welcome to JTL!"
    )

    try:
        sms = africastalking.SMS
        response = sms.send(
            message,
            [phone_number],
            sender_id=settings.at_sender_id if settings.at_sender_id else None,
        )
        logger.info(
            "wifi_sms_sent",
            phone=phone_number,
            customer=customer_id,
            response=str(response),
        )
        return True
    except Exception:
        logger.exception("wifi_sms_failed", phone=phone_number, customer=customer_id)
        return False
