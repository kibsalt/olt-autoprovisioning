"""WiFi credential generation utilities."""
import secrets
import string

_CHARS = string.ascii_letters + string.digits


def generate_wifi_credentials(customer_id: str) -> dict:
    """Generate WiFi credentials following JTL SSID naming convention.

    SSID format: JTL-{customer_short_id}-2G / JTL-{customer_short_id}-5G
    customer_short_id = first 8 chars of customer_id, uppercased, alphanumeric only
    """
    short_id = "".join(c for c in customer_id.upper() if c.isalnum())[:8]
    if not short_id:
        short_id = "CUSTOMER"
    ssid_2g = f"JTL-{short_id}-2G"
    ssid_5g = f"JTL-{short_id}-5G"
    password = "".join(secrets.choice(_CHARS) for _ in range(12))
    return {
        "ssid_2g": ssid_2g,
        "ssid_5g": ssid_5g,
        "password": password,
    }
