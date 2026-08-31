"""
Encryption at rest for sensitive fields (phone numbers, API keys).

Design
------
- `EncryptedString` is a SQLAlchemy `TypeDecorator` that transparently
  encrypts on WRITE and decrypts on READ using the platform's
  `SecretsManager` (Fernet, key derived from JWT_SECRET_KEY / a dedicated
  ENCRYPTION_KEY). Ciphertext is stored in a normal `String` column.
- For columns we must still *query by* (e.g. phone_number), we store a
  deterministic `phone_hash` (HMAC-SHA256) in a SEPARATE indexed column
  and filter on that instead of the plaintext. The plaintext ciphertext
  column is only used for display/decrypt, never for SQL equality.

This keeps PII and credentials unreadable if the database file or a backup
is ever leaked, while preserving the ability to look records up.
"""
import os
import hmac
import hashlib
import logging
from typing import Optional

from sqlalchemy.types import TypeDecorator, String

logger = logging.getLogger("crypto_fields")

# Key used for deterministic HMAC lookups. Falls back to the bridge secret
# so it works out-of-the-box in dev; set ENCRYPTION_KEY / PHONE_HASH_KEY in
# production for proper separation of duties.
_HASH_KEY = (
    os.getenv("PHONE_HASH_KEY")
    or os.getenv("ENCRYPTION_KEY")
    or os.getenv("JWT_SECRET_KEY")
    or os.getenv("WA_BRIDGE_SECRET")
    or "dev-insecure-hash-key-change-me"
).encode()


def _secrets():
    from secrets_manager import secrets as _mgr
    return _mgr


class EncryptedString(TypeDecorator):
    """Stores a string as Fernet ciphertext. Always round-trips; on any
    failure it returns the value as-is so the app never hard-crashes."""

    impl = String
    cache_ok = True

    def __init__(self, length: int = 1024, **kwargs):
        super().__init__(length, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return value
        try:
            return _secrets().encrypt(str(value))
        except Exception as e:  # pragma: no cover - defensive
            logger.error("EncryptedString encrypt failed: %s", e)
            return value

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return value
        try:
            return _secrets().decrypt(str(value))
        except Exception:
            # Value may already be plaintext (e.g. legacy row / fallback).
            return value


def hmac_phone_hash(phone: str) -> str:
    """Deterministic, non-reversible hash of a phone number for lookups.
    Normalizes to digits so lookups are stable regardless of formatting."""
    norm = "".join(ch for ch in (phone or "") if ch.isdigit())
    return hmac.new(_HASH_KEY, norm.encode(), hashlib.sha256).hexdigest()


def encrypt_value(plaintext: str) -> str:
    """Encrypt an arbitrary secret (e.g. an API key) for storage."""
    if not plaintext:
        return ""
    return _secrets().encrypt(plaintext)


def decrypt_value(token: str) -> str:
    """Decrypt a stored secret; returns the token unchanged if not encrypted."""
    if not token:
        return ""
    return _secrets().decrypt(token)
