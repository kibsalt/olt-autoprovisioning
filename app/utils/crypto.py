from cryptography.fernet import Fernet

from app.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        if not settings.credential_encryption_key:
            raise RuntimeError(
                "OLT_CREDENTIAL_ENCRYPTION_KEY must be set for credential encryption"
            )
        _fernet = Fernet(settings.credential_encryption_key.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def generate_key() -> str:
    """Generate a new Fernet key. Run once during initial setup."""
    return Fernet.generate_key().decode()
