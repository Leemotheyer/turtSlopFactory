import base64
import hashlib

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    from app.services.instance_bootstrap import ensure_encryption_key

    key = ensure_encryption_key()
    if len(key) != 44:
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
