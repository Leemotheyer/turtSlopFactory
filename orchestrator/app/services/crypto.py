import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from app.config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    key = settings.secrets_encryption_key
    if not key:
        derived = hashlib.sha256(b"turtslop-factory-dev-key").digest()
        key = base64.urlsafe_b64encode(derived)
        logger.warning("Using dev secrets encryption key — set SECRETS_ENCRYPTION_KEY in production")
    elif len(key) != 44:
        derived = hashlib.sha256(key.encode()).digest()
        key = base64.urlsafe_b64encode(derived)
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def mask_value(value: str) -> str:
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]
