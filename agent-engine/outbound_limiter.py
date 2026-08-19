"""
Outbound Rate Limiter - Per-number daily cap, per-recipient cooldown, randomized delay.
Uses Redis if available, falls back to in-memory dict.
"""
import os
import time
import random
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("outbound_limiter")

try:
    import redis
    _redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    _redis_client.ping()
    _USE_REDIS = True
except Exception:
    _redis_client = None
    _USE_REDIS = False

_DAILY_CAP = int(os.getenv("OUTBOUND_DAILY_CAP", "1000"))
_COOLDOWN_SECONDS = int(os.getenv("OUTBOUND_COOLDOWN_SECONDS", "300"))
_INMEMORY: dict = {}


def _get_day_key(phone_number: str) -> str:
    now = datetime.now(timezone.utc)
    return f"outbound:{phone_number}:{now.strftime('%Y%m%d')}"


def _get_cooldown_key(phone_number: str) -> str:
    return f"outbound:cooldown:{phone_number}"


def check_can_send(phone_number: str) -> bool:
    """Return True if we can send to this number right now."""
    day_key = _get_day_key(phone_number)
    cooldown_key = _get_cooldown_key(phone_number)
    if _USE_REDIS and _redis_client:
        count = int(_redis_client.get(day_key) or 0)
        if count >= _DAILY_CAP:
            logger.warning("Daily cap reached for %s: %s/%s", phone_number, count, _DAILY_CAP)
            return False
        if _redis_client.exists(cooldown_key):
            logger.warning("Cooldown active for %s", phone_number)
            return False
        return True
    else:
        data = _INMEMORY.get(phone_number, {})
        day_count = data.get("day_count", 0)
        day_key_local = _get_day_key(phone_number)
        if data.get("day_key") != day_key_local:
            day_count = 0
        if day_count >= _DAILY_CAP:
            logger.warning("Daily cap reached for %s: %s/%s", phone_number, day_count, _DAILY_CAP)
            return False
        last_send = data.get("last_send", 0)
        if time.time() - last_send < _COOLDOWN_SECONDS:
            logger.warning("Cooldown active for %s", phone_number)
            return False
        return True


def record_send(phone_number: str):
    """Record a successful send to this number."""
    day_key = _get_day_key(phone_number)
    cooldown_key = _get_cooldown_key(phone_number)
    if _USE_REDIS and _redis_client:
        pipe = _redis_client.pipeline()
        pipe.incr(day_key)
        pipe.expire(day_key, 86400 + 60)
        pipe.set(cooldown_key, "1", ex=_COOLDOWN_SECONDS)
        pipe.execute()
    else:
        if phone_number not in _INMEMORY:
            _INMEMORY[phone_number] = {}
        _INMEMORY[phone_number]["day_key"] = day_key
        _INMEMORY[phone_number]["day_count"] = _INMEMORY[phone_number].get("day_count", 0) + 1
        _INMEMORY[phone_number]["last_send"] = time.time()


def get_delay() -> float:
    """Return randomized delay between 5 and 15 seconds."""
    return random.uniform(5.0, 15.0)
