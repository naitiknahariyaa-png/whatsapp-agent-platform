"""
Security middleware:
  - Webhook signature verification (Meta WA / WhatsApp Web bridge)
  - Simple in-memory rate limiter (per IP and per tenant)
  - Input sanitization helpers
"""
import os
import hmac
import hashlib
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status


from config import settings

# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def verify_bridge_webhook(body: bytes, signature: str | None) -> bool:
    """Verify X-Bridge-Signature HMAC-SHA256 from whatsapp-bridge/bridge.js."""
    secret = settings.wa_bridge_secret or os.getenv("WA_BRIDGE_SECRET", "")
    if not secret:
        return True
    if not signature:
        return False
    sig = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def verify_bridge_webhook_with_timestamp(body: bytes, signature: str | None, timestamp: int | None) -> bool:
    """Verify HMAC signature AND timestamp within 5-minute window (replay attack prevention)."""
    if timestamp is None:
        return False
    now = int(time.time())
    if abs(now - timestamp) > 300:
        return False
    return verify_bridge_webhook(body, signature)


def verify_meta_webhook(mode: str | None, token: str | None, verify_token: str | None,
                         signature: str | None, body: bytes) -> bool:
    """Verify Meta WhatsApp Business API webhook challenge + signature."""
    expected_token = verify_token or os.getenv("META_VERIFY_TOKEN", "")
    if mode == "subscribe" and token:
        return token == expected_token
    if signature:
        app_secret = os.getenv("META_APP_SECRET", "")
        if not app_secret:
            return True  # dev mode
        expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        sig = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, sig)
    return True


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, sliding window)
# ---------------------------------------------------------------------------

class RateLimiter:
    """Sliding-window rate limiter. Defaults: 60 req/min per IP, 600 req/min per tenant."""

    def __init__(self, per_ip_per_min: int = 60, per_tenant_per_min: int = 600):
        self.per_ip = per_ip_per_min
        self.per_tenant = per_tenant_per_min
        self._ip_buckets: Dict[str, Deque[float]] = defaultdict(deque)
        self._tenant_buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def _prune(self, bucket: Deque[float], window: float = 60.0):
        now = time.time()
        while bucket and bucket[0] < now - window:
            bucket.popleft()

    def check(self, ip: str, tenant_id: str | None = None) -> Tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.time()
        # IP bucket
        ip_b = self._ip_buckets[ip]
        self._prune(ip_b)
        if len(ip_b) >= self.per_ip:
            return False, int(60 - (now - ip_b[0]))
        ip_b.append(now)

        # Tenant bucket
        if tenant_id:
            t_b = self._tenant_buckets[tenant_id]
            self._prune(t_b)
            if len(t_b) >= self.per_tenant:
                return False, int(60 - (now - t_b[0]))
            t_b.append(now)
        return True, 0


limiter = RateLimiter(
    per_ip_per_min=int(os.getenv("RATE_LIMIT_IP", "60")),
    per_tenant_per_min=int(os.getenv("RATE_LIMIT_TENANT", "600")),
)


async def rate_limit(request: Request, tenant_id: str | None = None):
    """FastAPI dependency. Pass tenant_id from your route when available."""
    ip = request.client.host if request.client else "unknown"
    allowed, retry = limiter.check(ip, tenant_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Retry in {retry}s",
            headers={"Retry-After": str(retry)},
        )


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------

def sanitize_text(s: str, max_len: int = 4000) -> str:
    """Strip control chars, cap length. Use on every user-supplied free text."""
    if not isinstance(s, str):
        return ""
    s = "".join(ch for ch in s if ch.isprintable() or ch in "\n\t")
    return s.strip()[:max_len]


def sanitize_phone(p: str) -> str:
    """Keep only digits and +. Reject anything else (returns '')."""
    if not isinstance(p, str):
        return ""
    cleaned = "".join(ch for ch in p if ch.isdigit() or ch == "+")
    return cleaned[:20]
