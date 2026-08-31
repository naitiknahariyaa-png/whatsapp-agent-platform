"""
Idempotency Keys — Part G reliability utility.

Guarantees that destructive/expensive operations (webhook processing, campaign
sends, payment webhooks) only execute once even if the client retries.  A Redis
key stores the response of the first execution; identical retries within the
TTL replay that stored response instead of re-running the side effect.

Usage::
    from idempotency import idempotent, idempotency_key

    async def process_payment(amount): ...

    result, dup = await idempotent(idempotency_key("pay", ref_id), lambda: process_payment(amount))
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import redis.asyncio as redis

from config import settings

logger = logging.getLogger("idempotency")

# In-memory fallback store used when Redis is unavailable (tests / local mode).
_mem_store: Dict[str, Dict[str, Any]] = {}

# Per-key asyncio locks give a same-process single-execution guarantee for
# concurrent idempotent() calls against the same key.
_locks: Dict[str, "asyncio.Lock"] = {}


def _get_lock(ik: str) -> "asyncio.Lock":
    if ik not in _locks:
        _locks[ik] = asyncio.Lock()
    return _locks[ik]


def _get_redis() -> Optional["redis.Redis"]:
    """Return a Redis client, or None when Redis is not reachable/configured."""
    try:
        return redis.from_url(
            getattr(settings, "redis_url", None) or "redis://localhost:6379/0",
            decode_responses=True,
            max_connections=10,
        )
    except Exception:
        return None



def idempotency_key(*parts: Any) -> str:
    """Build a stable, hashed idempotency key from the given parts.

    Any combination of raw values is normalised to a 64-char SHA-256 hex so
    keys never leak PII into Redis and are immune to formatting inconsistencies.
    """
    canonical = "|".join(str(p).strip().lower() for p in parts if p is not None)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def get_result(ik: str, ttl_seconds: int = 86400) -> Optional[Any]:
    """Return the stored first-run result for *ik*, or None if not seen."""
    r = _get_redis()
    if r is not None:
        try:
            prev = await r.get(f"idem:{ik}")
            if prev is not None:
                try:
                    return json.loads(prev).get("result")
                except Exception:
                    return prev
        except Exception as exc:
            logger.debug("[!] idempotency read failed: %s", exc)
    for stored in list(_mem_store.keys()):
        entry = _mem_store[stored]
        if stored == ik and entry["expires"] > time.time():
            try:
                return entry["value"].get("result")
            except Exception:
                return entry["value"]
    return None


async def was_processed(ik: str, result: Any = None, ttl_seconds: int = 86400) -> bool:
    """Return True if this idempotency key was already seen, storing it if new."""
    r = _get_redis()
    stored = json.dumps({"result": result, "ts": time.time()}) if result is not None else "1"
    if r is not None:
        try:
            ok = await r.set(f"idem:{ik}", stored, nx=True, ex=ttl_seconds)
            return ok is None  # None => key already existed => duplicate
        except Exception as exc:
            logger.debug("[!] idempotency set failed: %s", exc)
    # in-memory fallback
    if ik in _mem_store and _mem_store[ik]["expires"] > time.time():
        return True
    _mem_store[ik] = {"value": {"result": result}, "expires": time.time() + ttl_seconds}
    return False


async def idempotent(
    ik: str,
    fn: Callable[[], Awaitable[Any]],
    ttl_seconds: int = 86400,
    store_result: bool = True,
) -> Tuple[Any, bool]:
    """Run *fn* exactly once per idempotency key.

    Returns ``(result, is_duplicate)`` where ``is_duplicate`` is True when the
    operation had already been performed (result is then the stored first-run
    result).
    """
    lock = _get_lock(ik)
    async with lock:
        prev = await get_result(ik, ttl_seconds=ttl_seconds)
        if prev is not None:
            return prev, True

        result = await fn()
        if store_result:
            await was_processed(ik, result=result, ttl_seconds=ttl_seconds)
        return result, False