"""
Security Utility Functions
HMAC verification, field encryption, rate limiting, and PII scrubbing.
"""
import base64
import hmac
import hashlib
import logging
import os
import re
import time
from typing import Optional, Dict, Any
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 8.1 verify_hmac_signature — Webhook authenticity
# ---------------------------------------------------------------------------
def verify_hmac_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256",
) -> bool:
    """
    Verifies HMAC signature for webhook authenticity.
    Prevents spoofed webhooks from sending fake events.

    Args:
        payload: Raw request body bytes
        signature: Signature header value (e.g., "sha256=abc123...")
        secret: Shared secret key
        algorithm: Hash algorithm (sha256, sha1, md5)

    Returns:
        True if signature is valid
    """
    if not signature or not secret:
        return False

    sig = signature.removeprefix(f"{algorithm}=")
    if algorithm == "sha256":
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    elif algorithm == "sha1":
        expected = hmac.new(secret.encode(), payload, hashlib.sha1).hexdigest()
    elif algorithm == "md5":
        expected = hmac.new(secret.encode(), payload, hashlib.md5).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    return hmac.compare_digest(expected, sig)


# ---------------------------------------------------------------------------
# 8.2 is_request_stale — Replay attack prevention
# ---------------------------------------------------------------------------
def is_request_stale(
    timestamp: Optional[int],
    max_age_seconds: int = 300,
) -> bool:
    """
    Checks if a request timestamp is too old (replay attack prevention).
    Use with webhook HMAC verification for full security.

    Args:
        timestamp: Unix timestamp from request
        max_age_seconds: Max acceptable age (default 5 minutes)

    Returns:
        True if request is stale (reject it)
    """
    if timestamp is None:
        return True

    now = int(time.time())
    age = abs(now - timestamp)
    return age > max_age_seconds


# ---------------------------------------------------------------------------
# 8.3 encrypt_field / decrypt_field — Simple field-level encryption
# ---------------------------------------------------------------------------
def _derive_key(secret: str, salt: bytes) -> bytes:
    """Derive a 32-byte key from secret + salt."""
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, 100000)


def encrypt_field(plaintext: str, secret: str) -> str:
    """
    Encrypt a field value for safe storage.
    Uses AES-256-GCM via base64-encoded nonce|ciphertext|tag.

    Args:
        plaintext: Value to encrypt
        secret: Encryption secret key

    Returns:
        Base64-encoded encrypted string
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        salt = os.urandom(16)
        key = _derive_key(secret, salt)
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        payload = salt + nonce + ciphertext
        return base64.b64encode(payload).decode()
    except ImportError:
        # Fallback: simple XOR obfuscation (NOT secure, but prevents plaintext leaks)
        logger.warning("cryptography not installed, using fallback obfuscation")
        key_bytes = hashlib.sha256(secret.encode()).digest()
        encoded = plaintext.encode()
        obfuscated = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encoded))
        return base64.b64encode(obfuscated).decode()


def decrypt_field(ciphertext_b64: str, secret: str) -> str:
    """
    Decrypt a field value.

    Args:
        ciphertext_b64: Base64-encoded encrypted string
        secret: Encryption secret key

    Returns:
        Decrypted plaintext string
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        payload = base64.b64decode(ciphertext_b64)
        salt = payload[:16]
        nonce = payload[16:28]
        ciphertext = payload[28:]
        key = _derive_key(secret, salt)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode()
    except ImportError:
        key_bytes = hashlib.sha256(secret.encode()).digest()
        obfuscated = base64.b64decode(ciphertext_b64)
        plaintext = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(obfuscated))
        return plaintext.decode()


# ---------------------------------------------------------------------------
# 8.4 rate_limit — Utility wrapper for per-entity rate limiting
# ---------------------------------------------------------------------------
class _RateLimiter:
    """Simple in-memory sliding window rate limiter."""

    def __init__(self):
        self._buckets: Dict[str, deque] = defaultdict(deque)

    def check(self, key: str, limit: int, window: int = 60) -> bool:
        """
        Check if key is within rate limit.

        Args:
            key: Rate limit key (e.g., "user:123", "ip:1.2.3.4")
            limit: Max requests in window
            window: Time window in seconds

        Returns:
            True if allowed, False if rate limited
        """
        now = time.time()
        bucket = self._buckets[key]
        while bucket and bucket[0] < now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


_rate_limiter = _RateLimiter()


def rate_limit(
    key: str,
    limit: int = 10,
    window: int = 60,
) -> bool:
    """
    Check rate limit for a given key.

    Args:
        key: Unique identifier (phone_number, user_id, ip_address)
        limit: Max requests in window
        window: Time window in seconds

    Returns:
        True if request is allowed
    """
    return _rate_limiter.check(key, limit, window)


# ---------------------------------------------------------------------------
# 8.5 scrub_pii_from_logs — Prevents data leaks
# ---------------------------------------------------------------------------
PII_PATTERNS = [
    (re.compile(r'\b\d{10,15}\b'), "[PHONE]"),
    (re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'), "[EMAIL]"),
    (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), "[PAN]"),
    (re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'), "[CARD]"),
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "[SSN]"),
    (re.compile(r'\b(?:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+', re.IGNORECASE), "[REDACTED]"),
]

SENSITIVE_KEYS = {
    "password", "secret", "token", "api_key", "authorization",
    "credit_card", "card_number", "cvv", "pin", "aadhaar", "pan",
}


def scrub_pii_from_logs(data: Any, _depth: int = 0) -> Any:
    """
    Recursively scrub PII from data structures before logging.
    Prevents accidental credential/PII leaks in logs.

    Args:
        data: Any data structure (dict, list, str, etc.)
        _depth: Internal recursion depth

    Returns:
        Scrubbed copy of data
    """
    if _depth > 10:
        return "[max depth]"

    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            if k.lower() in SENSITIVE_KEYS:
                scrubbed[k] = "[REDACTED]"
            else:
                scrubbed[k] = scrub_pii_from_logs(v, _depth + 1)
        return scrubbed

    if isinstance(data, list):
        return [scrub_pii_from_logs(item, _depth + 1) for item in data]

    if isinstance(data, str):
        result = data
        for pattern, replacement in PII_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    return data
