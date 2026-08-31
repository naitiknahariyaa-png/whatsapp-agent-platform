"""
Central Event Bus - Part H of the WhatsApp Agent Platform.

Redis Pub/Sub event bus: workers/loops/mutations publish structured
events -> WebSocket gateway fans them out to connected browser clients.

Design:
  * Events are JSON dicts: {type, owner_id, timestamp, payload}
  * Each owner gets channel  wa:event:{owner_id}
  * In-process fallback (asyncio.Queue) when Redis is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable, Awaitable

import redis.asyncio as redis

from config import settings

logger = logging.getLogger("event_bus")

EVENT_BUS_REDIS_KEY = "wa:event_bus:running"


def owner_channel(owner_id: int) -> str:
    return f"wa:event:{owner_id}"


@dataclass
class EventBusEvent:
    type: str
    owner_id: int
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "owner_id": self.owner_id,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "ts": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
        }


class EventBus:
    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url or getattr(settings, "redis_url", None) or "redis://localhost:6379/0"
        self._pub: Optional[redis.Redis] = None
        self._sub: Optional[redis.Redis] = None
        self._subscribed: bool = False
        self._sub_task: Optional[asyncio.Task] = None
        self._fallback_queue: Optional[asyncio.Queue] = None
        self._using_fallback: bool = False
        self._handlers: List[Callable] = []

    async def start(self) -> None:
        try:
            self._pub = redis.from_url(self._redis_url, decode_responses=True, max_connections=20)
            self._sub = redis.from_url(self._redis_url, decode_responses=True, max_connections=20)
            await self._pub.ping()
            logger.info("[v] EventBus connected to Redis: %s", self._redis_url)
            self._sub_task = asyncio.create_task(self._subscribe_loop())
        except Exception as exc:
            logger.warning("[!] EventBus Redis unavailable (%s); using in-process fallback.", exc)
            self._using_fallback = True
            self._fallback_queue = asyncio.Queue(maxsize=500)
            self._sub_task = asyncio.create_task(self._fallback_loop())

    async def stop(self) -> None:
        """Stop the subscriber task and close Redis connections."""
        self._subscribed = False
        if self._sub_task:
            self._sub_task.cancel()
            try:
                await self._sub_task
            except asyncio.CancelledError:
                pass
        for r in (self._pub, self._sub):
            if r:
                try:
                    await r.close()
                except Exception:
                    pass
        logger.info("[v] EventBus stopped")

    async def publish(self, event: EventBusEvent) -> bool:
        """Publish *event* to the owner channel. Returns True on success."""
        data = json.dumps(event.to_dict())
        if self._using_fallback:
            try:
                await self._fallback_queue.put(event)
                return True
            except asyncio.QueueFull:
                return False
        try:
            await self._pub.publish(owner_channel(event.owner_id), data)
            return True
        except Exception as exc:
            logger.error("[!] EventBus publish failed: %s", exc)
            await self._dispatch_local(event)
            return True

    async def publish_dict(self, event_type: str, owner_id: int, payload: Optional[Dict[str, Any]] = None) -> bool:
        """Convenience: publish a raw dict instead of constructing EventBusEvent."""
        return await self.publish(EventBusEvent(type=event_type, owner_id=owner_id, payload=payload or {}))

    def add_handler(self, handler: Callable[[EventBusEvent], Awaitable[None]]) -> None:
            """Register an in-process async handler that receives every event."""
            self._handlers.append(handler)

    async def _subscribe_loop(self) -> None:
        """Background task: subscribe to all owner channels and dispatch."""
        if not self._sub:
            return
        try:
            await self._sub.psubscribe("wa:event:*")
            self._subscribed = True
            logger.info("[v] EventBus subscribed to wa:event:*")
            while True:
                msg = await self._sub.get_message(timeout=1.0, ignore_subscribed=True)
                if msg and msg.get("type") == "pmessage":
                    try:
                        data = json.loads(msg["data"])
                        event = EventBusEvent(
                            type=data["type"],
                            owner_id=data["owner_id"],
                            payload=data.get("payload", {}),
                            correlation_id=data.get("correlation_id", str(uuid.uuid4())),
                            timestamp=data.get("timestamp", time.time()),
                        )
                        await self._dispatch_local(event)
                    except Exception as exc:
                        logger.error("[!] EventBus dispatch error: %s", exc)
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("[!] EventBus subscriber loop error: %s", exc)
        finally:
            try:
                await self._sub.punsubscribe()
            except Exception:
                pass

    async def _fallback_loop(self) -> None:
        """In-process fallback: drain the queue and dispatch locally."""
        if not self._fallback_queue:
            return
        while True:
            try:
                event = await self._fallback_queue.get()
                await self._dispatch_local(event)
            except Exception as exc:
                logger.error("[!] EventBus fallback dispatch error: %s", exc)
            await asyncio.sleep(0.01)

    async def _dispatch_local(self, event: EventBusEvent) -> None:
        """Run all registered handlers with the event (best-effort)."""
        for handler in self._handlers:
            try:
                await handler(event)
            except Exception as exc:
                name = getattr(handler, "__name__", "unknown")
                logger.error("[!] EventBus handler error (%s): %s", name, exc)

    @property
    def is_fallback(self) -> bool:
        return self._using_fallback

    async def get_status(self) -> Dict[str, Any]:
        """Return runtime status for health checks."""
        status: Dict[str, Any] = {
            "connected": self._pub is not None and not self._using_fallback,
            "using_fallback": self._using_fallback,
            "subscribed": self._subscribed,
            "handlers": len(self._handlers),
        }
        if self._pub and not self._using_fallback:
            try:
                await self._pub.ping()
                status["ping"] = "ok"
            except Exception:
                status["ping"] = "failed"
        return status


# ── process-wide singleton ──────────────────────────────────────
_event_bus: Optional["EventBus"] = None


def get_event_bus() -> "EventBus":
    """Return the singleton EventBus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset the singleton (used in tests)."""
    global _event_bus
    _event_bus = None
