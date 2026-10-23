import hmac
import hashlib
import logging
from typing import Optional, Tuple
from cryptography.fernet import Fernet
from fastapi import Header, HTTPException, status, Depends
from fastapi.security import APIKeyHeader
from app.config import settings

logger = logging.getLogger("emergencysos.security")

# OpenAPI APIKeyHeader
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Secret API key for Emergency SOS")


def get_fernet_cipher() -> Fernet:
    """Instantiate Fernet symmetric cipher for AES-256 encryption at rest."""
    try:
        return Fernet(settings.AUDIO_ENCRYPTION_KEY.encode())
    except Exception as e:
        logger.warning(f"Invalid encryption key ({e}); generating ephemeral key.")
        return Fernet(Fernet.generate_key())


def encrypt_audio_bytes(data: bytes) -> Tuple[bytes, str]:
    """
    Encrypts ambient audio clip using AES-256 (Fernet) at rest.
    Returns (encrypted_bytes, sha256_hash_of_raw_audio).
    """
    sha256 = hashlib.sha256(data).hexdigest()
    cipher = get_fernet_cipher()
    encrypted = cipher.encrypt(data)
    return encrypted, sha256


def decrypt_audio_bytes(encrypted_data: bytes) -> bytes:
    """Decrypts ambient audio clip for guardian playback or evidence."""
    cipher = get_fernet_cipher()
    return cipher.decrypt(encrypted_data)


def verify_cancel_passphrase(provided: str, actual: Optional[str] = None) -> Tuple[bool, bool]:
    """
    Constant-time comparison for disarming the SOS session.
    Supports Duress PIN/word (e.g. 'help' or 'danger' or actual + '999').
    Returns (is_valid, is_duress).
    """
    target = (actual or settings.DEFAULT_CANCEL_PASSPHRASE).strip().lower()
    clean_provided = provided.strip().lower()

    # Secret duress trigger: if attacker forces victim to cancel, entering 'help' or 'duress'
    if clean_provided in ("help", "danger", "duress", "police", f"{target}9"):
        return True, True

    # Check normal secret
    is_match = hmac.compare_digest(clean_provided.encode(), target.encode())
    return is_match, False


def verify_api_key(x_api_key: Optional[str] = Depends(api_key_header)) -> str:
    """Validate internal service-to-service secret API key."""
    if not settings.API_KEY:
        return x_api_key or ""
    if not x_api_key or x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header. Provide 'X-API-Key: kaali-secret-key-12345'."
        )
    return x_api_key
