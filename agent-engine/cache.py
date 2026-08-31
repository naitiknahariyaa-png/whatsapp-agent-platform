"""
Redis-backed cache - Part A.6 of the WhatsApp Agent Platform.

Cache-aside caching for hot reads (business profiles, catalog) with
EXPLICIT invalidation on every mutation. Never relies on TTL alone.

Design:
  * JSON-serializable values only.
  * Keys namespaced under wa:cache:* so the whole app cache can be
    swept or selectively invalidated by prefix.
  * In-memory fallback dict when Redis is unavailable, so local /
    offline mode still works. The fallback is process-local, which is
    acceptable degradation; Redis is the real deployment path.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import redis as redis_sync

from config import settings

logger = logging.getLogger("cache")

CACHE_PREFIX = "wa:cache"
DEFAULT_TTL_SECONDS = 300


def profile_key(business_id: str) -> str:
    return f"{CACHE_PREFIX}:profile:{business_id}"


def catalog_key(business_id: str, category: str = "") -> str:
    return f"{CACHE_PREFIX}:catalog:{business_id}:{category or '_all'}"


def stats_key(business_id: str) -> str:
    return f"{CACHE_PREFIX}:stats:{business_id}"


class Cache:
    """Sync cache-aside helper: get/set/delete + pattern invalidation."""

    def __init__(self, redis_url: Optional[str] = None):
        self._url = redis_url or settings.redis_url
        self._client: Optional[redis_sync.Redis] = None
        self._memory: Dict[str, str] = {}
        self._using_memory = False

    def connect(self) -> bool:
        """Ping Redis once; fall back to in-memory on failure."""
        if self._client is not None:
            return not self._using_memory
        try:
            client = redis_sync.from_url(self._url, decode_responses=True,
                                         socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            self._client = client
            self._using_memory = False
            logger.info("[v] Cache connected to Redis: %s", self._url)
            return True
        except Exception as exc:
            logger.warning("[!] Cache Redis unavailable (%s); using in-process fallback.", exc)
            self._using_memory = True
            return False

    @property
    def is_redis(self) -> bool:
        return self._client is not None and not self._using_memory

    # ---- basic ops -------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        try:
            if self.is_redis:
                raw = self._client.get(key)
                return json.loads(raw) if raw is not None else None
            raw = self._memory.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception as exc:
            logger.warning("[!] Cache get failed for %s: %s", key, exc)
            return None

    def set(self, key: str, value: Any, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        try:
            raw = json.dumps(value, default=str)
            if self.is_redis:
                self._client.set(key, raw, ex=ttl)
            else:
                self._memory[key] = raw
            return True
        except Exception as exc:
            logger.warning("[!] Cache set failed for %s: %s", key, exc)
            return False

    def delete(self, *keys: str) -> int:
        """Explicit invalidation of exact keys."""
        keys = [k for k in keys if k]
        if not keys:
            return 0
        deleted = 0
        try:
            if self.is_redis:
                deleted = self._client.delete(*keys)
            else:
                for k in keys:
                    if self._memory.pop(k, None) is not None:
                        deleted += 1
        except Exception as exc:
            logger.warning("[!] Cache delete failed for %s: %s", keys, exc)
        return deleted

    # ---- pattern invalidation --------------------------------------

    def invalidate_prefix(self, pattern: str) -> int:
        """Delete every key matching e.g. 'catalog:BIZ123:*' (auto-namespaced)."""
        full = pattern if pattern.startswith(CACHE_PREFIX) else f"{CACHE_PREFIX}:{pattern}"
        deleted = 0
        try:
            if self.is_redis:
                cursor = 0
                while True:
                    cursor, found = self._client.scan(cursor=cursor, match=full, count=200)
                    if found:
                        deleted += self._client.delete(*found)
                    if cursor == 0:
                        break
            else:
                targets = [k for k in list(self._memory) if _glob_match(full, k)]
                for k in targets:
                    self._memory.pop(k, None)
                    deleted += 1
        except Exception as exc:
            logger.warning("[!] Cache invalidate failed for %s: %s", full, exc)
        return deleted

    def invalidate_business(self, business_id: str) -> int:
        """Invalidate everything cached about one business."""
        n = self.delete(profile_key(business_id), stats_key(business_id))
        n += self.invalidate_prefix(f"catalog:{business_id}:*")
        return n


def _glob_match(pattern: str, text: str) -> bool:
    """Minimal '*' glob matcher used by the in-memory fallback."""
    parts = pattern.split("*")
    pos = 0
    for i, part in enumerate(parts):
        if part == "":
            continue
        idx = text.find(part, pos)
        if i == 0 and idx != 0:
            return False
        if idx == -1:
            return False
        pos = idx + len(part)
    if parts[-1] != "" and not text.endswith(parts[-1]):
        return False
    return True


# Shared instance for the whole backend process.
cache = Cache()

