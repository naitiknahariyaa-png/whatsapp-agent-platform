"""
Outbound Rate Limiter & Anti-Ban Queue
======================================
Production-hardened outbound WhatsApp sender.

Guarantees (anti-ban):
  - Per-RECIPIENT cooldown so we never hammer one number.
  - Per-NUMBER daily send cap (default 1000/day).
  - Randomized 5-20s delay between sends (WhatsApp "human-like" spacing).
  - Redis-backed durable queue: jobs survive a process restart and are
    drained by a single worker that enforces global spacing.

All state is Redis-backed when Redis is available, with an in-memory
fallback for local/dev use.
"""
import os
import time
import random
import asyncio
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
_MIN_DELAY = float(os.getenv("OUTBOUND_MIN_DELAY", "5.0"))
_MAX_DELAY = float(os.getenv("OUTBOUND_MAX_DELAY", "20.0"))
_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:3001")
_QUEUE_KEY = os.getenv("OUTBOUND_QUEUE_KEY", "outbound_queue")
_GLOBAL_SPACING = float(os.getenv("OUTBOUND_GLOBAL_SPACING", "2.0"))
_INMEMORY: dict = {}
_LAST_SEND_TS = 0.0
_LOCK = asyncio.Lock()

# Opt-out keyword set — checked before every outbound send so we never message
# someone who has explicitly opted out. Mirrors the set in lead_funnel.py.
OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "बंद", "रद्द", "opt out", "end", "quit"}
_opted_out_phones: set = set()
_opt_out_store_key = "outbound:opted_out"


# ---------------------------------------------------------------------------
# Low-level counters (Redis-backed)
# ---------------------------------------------------------------------------

def _get_day_key(phone_number: str) -> str:
    now = datetime.now(timezone.utc)
    return f"outbound:{phone_number}:{now.strftime('%Y%m%d')}"


def _get_cooldown_key(phone_number: str) -> str:
    return f"outbound:cooldown:{phone_number}"


def check_can_send(phone_number: str) -> bool:
    """Return True if we can send to this number right now (cap + cooldown)."""
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
    """Record a successful send to this number (increment cap + set cooldown)."""
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
    """Return a randomized human-like delay between 5 and 20 seconds."""
    return random.uniform(_MIN_DELAY, _MAX_DELAY)


# ---------------------------------------------------------------------------
# Opt-out registry
# ---------------------------------------------------------------------------


def _normalize_phone(phone: str) -> str:
    """Normalize a phone number to digits-only for set comparison."""
    if not phone:
        return ""
    return "".join(ch for ch in phone if ch.isdigit())


def is_opted_out(phone_number: str) -> bool:
    """Return True if the phone number has explicitly opted out."""
    norm = _normalize_phone(phone_number)
    if not norm:
        return False
    if _USE_REDIS and _redis_client:
        try:
            return bool(_redis_client.sismember(_opt_out_store_key, norm))
        except Exception:
            pass
    return norm in _opted_out_phones


def record_opt_out(phone_number: str) -> None:
    """Mark a phone number as opted-out so no further outbound messages are sent."""
    norm = _normalize_phone(phone_number)
    if not norm:
        return
    if _USE_REDIS and _redis_client:
        try:
            _redis_client.sadd(_opt_out_store_key, norm)
        except Exception:
            pass
    _opted_out_phones.add(norm)
    logger.info("Opt-out recorded for %s", norm)


def is_opt_out_message(message: str) -> bool:
    """Check if an incoming message is an opt-out request."""
    if not message:
        return False
    msg_lower = message.lower().strip()
    return any(kw in msg_lower for kw in OPT_OUT_KEYWORDS)


# ---------------------------------------------------------------------------
# Direct sender (applies delay + cap + cooldown + opt-out check)
# ---------------------------------------------------------------------------

async def send_whatsapp(to: str, message: str, client_id: int = 1) -> bool:
    """
    Send a WhatsApp message respecting anti-ban limits + opt-out checks.

    Returns True if sent, False if blocked by cap/cooldown/opt-out or the
    bridge is unreachable. Never raises.
    """
    global _LAST_SEND_TS

    # --- Anti-ban: refuse to message anyone who has opted out ---
    if is_opted_out(to):
        logger.warning("Opt-out active for %s — message suppressed", to)
        return False

    if not check_can_send(to):
        return False
    # Human-like randomized delay + a minimum global spacing between sends.
    delay = get_delay()
    async with _LOCK:
        since_last = time.time() - _LAST_SEND_TS
        if since_last < _GLOBAL_SPACING:
            delay = max(delay, _GLOBAL_SPACING - since_last)
        await asyncio.sleep(delay)
        _LAST_SEND_TS = time.time()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_BRIDGE_URL}/send",
                json={"to": to, "message": message},
            )
            if resp.status_code == 200:
                record_send(to)
                logger.info("Sent WA to %s (client=%s)", to, client_id)
                return True
            logger.warning("Bridge rejected send to %s: %s", to, resp.status_code)
            return False
    except Exception as e:
        logger.error("Outbound send failed for %s: %s", to, e)
        return False


# ---------------------------------------------------------------------------
# Redis-backed durable queue + single worker
# ---------------------------------------------------------------------------

class OutboundQueue:
    """Durable outbound queue. Jobs are pushed to Redis (or memory) and
    drained by one worker that enforces anti-ban spacing + caps."""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def enqueue(self, to: str, message: str, client_id: int = 1) -> None:
        job = {"to": to, "message": message, "client_id": client_id}
        if _USE_REDIS and _redis_client:
            _redis_client.rpush(_QUEUE_KEY, _json_dumps(job))
        else:
            _INMEMORY.setdefault("_queue", []).append(job)

    async def _pop(self):
        if _USE_REDIS and _redis_client:
            raw = _redis_client.lpop(_QUEUE_KEY)
            return _json_loads(raw) if raw else None
        q = _INMEMORY.get("_queue")
        if q:
            return q.pop(0)
        return None

    async def _loop(self):
        while self._running:
            try:
                job = await self._pop()
                if not job:
                    await asyncio.sleep(1.0)
                    continue
                await send_whatsapp(job["to"], job["message"], job.get("client_id", 1))
            except Exception as e:  # pragma: no cover - defensive
                logger.error("Outbound queue worker error: %s", e)
                await asyncio.sleep(1.0)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[v] Outbound queue worker started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("[i] Outbound queue worker stopped")


def _json_dumps(obj):
    import json
    return json.dumps(obj)


def _json_loads(raw):
    import json
    try:
        return json.loads(raw)
    except Exception:
        return None


# Global instances
outbound_queue = OutboundQueue()

# Public alias for reuse by import pipelines (broadcast CLI etc.)
def normalize_phone_number(raw: str) -> str:
    """Public wrapper around the internal phone normalizer (E.164-ish)."""
    return _normalize_phone(raw)

