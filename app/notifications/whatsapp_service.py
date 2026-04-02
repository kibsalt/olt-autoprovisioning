"""WhatsApp notification service via Africa's Talking."""
import structlog
from app.config import settings

logger = structlog.get_logger()

_at_client = None


def _init_at():
    global _at_client
    if _at_client is None and settings.at_api_key and settings.at_whatsapp_sender:
        try:
            import africastalking
            africastalking.initialize(settings.at_username, settings.at_api_key)
            _at_client = africastalking.Application
        except Exception as exc:
            logger.warning("at_whatsapp_init_failed", error=str(exc))
    return _at_client


async def send_wifi_credentials_whatsapp(
    phone_number: str,
    customer_name: str,
    ssid_2g: str,
    ssid_5g: str,
    password: str,
) -> bool:
    """Send WiFi credentials via WhatsApp. Returns False if not configured."""
    if not settings.at_whatsapp_sender:
        return False
    client = _init_at()
    if client is None:
        return False
    try:
        import africastalking
        whatsapp = africastalking.WhatsApp
        msg = (
            f"Hello {customer_name},\n\n"
            f"Your JTL WiFi credentials are ready:\n"
            f"📶 2.4GHz SSID: {ssid_2g}\n"
            f"📶 5GHz SSID: {ssid_5g}\n"
            f"🔑 Password: {password}\n\n"
            f"Welcome to JTL!"
        )
        response = whatsapp.send(
            message=msg,
            sender_id=settings.at_whatsapp_sender,
            to=[phone_number],
        )
        logger.info(
            "whatsapp_sent",
            phone=phone_number,
            response=str(response)[:200],
        )
        return True
    except Exception as exc:
        logger.error("whatsapp_send_failed", phone=phone_number, error=str(exc))
        return False
