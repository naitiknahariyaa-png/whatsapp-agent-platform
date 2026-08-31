"""
Tests for the Part G/H reliability additions:
  - Central Event Bus (Redis Pub/Sub with in-process fallback)
  - Idempotency key deduplication
  - Alert manager quiet-hours suppression

NOTE: conftest.py points REDIS_URL at an unreachable address so these
components exercise their in-memory fallback paths during tests.
"""
import asyncio
import os
import sys

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import pytest

from event_bus import (
    EventBus,
    EventBusEvent,
    get_event_bus,
    reset_event_bus,
    owner_channel,
)
from idempotency import idempotency_key, idempotent, was_processed, get_result
from alerts import AlertManager, Alert, _load_thresholds


# ────────────────────────────────────────────────────────────────
# Part H: Event Bus
# ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_owner_channel_naming():
    assert owner_channel(1) == "wa:event:1"
    assert owner_channel(42) == "wa:event:42"


@pytest.mark.asyncio
async def test_event_bus_to_dict():
    e = EventBusEvent(type="appointment_booked", owner_id=7, payload={"phone": "+91"})
    d = e.to_dict()
    assert d["type"] == "appointment_booked"
    assert d["owner_id"] == 7
    assert d["payload"] == {"phone": "+91"}
    assert "correlation_id" in d
    assert "ts" in d


@pytest.mark.asyncio
async def test_event_bus_fallback_publish_dispatches_to_handler():
    reset_event_bus()
    bus = get_event_bus()
    await bus.start()  # Redis unreachable -> fallback mode
    assert bus.is_fallback is True

    received = []

    async def handler(event: EventBusEvent):
        received.append(event)

    bus.add_handler(handler)
    ok = await bus.publish_dict("campaign.sent", owner_id=3, payload={"n": 5})
    assert ok is True

    # Give the background fallback loop a chance to drain the queue
    for _ in range(20):
        if received:
            break
        await asyncio.sleep(0.02)

    assert len(received) == 1
    assert received[0].type == "campaign.sent"
    assert received[0].owner_id == 3
    await bus.stop()


@pytest.mark.asyncio
async def test_event_bus_status():
    reset_event_bus()
    bus = get_event_bus()
    await bus.start()
    status = await bus.get_status()
    assert status["using_fallback"] is True
    assert status["connected"] is False
    await bus.stop()


# ────────────────────────────────────────────────────────────────
# Part G: Idempotency
# ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_idempotency_key_deterministic():
    a = idempotency_key("pay", "REF-1", 100)
    b = idempotency_key("pay", "REF-1", 100)
    c = idempotency_key("pay", "REF-2", 100)
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_idempotent_fires_once():
    calls = []
    ik = idempotency_key("op", "unique-xyz")

    async def op():
        calls.append(1)
        return {"ok": True}

    r1, dup1 = await idempotent(ik, op)
    r2, dup2 = await idempotent(ik, op)

    assert dup1 is False
    assert dup2 is True
    assert len(calls) == 1
    assert r2 == {"ok": True}


@pytest.mark.asyncio
async def test_was_processed_tracks():
    ik = idempotency_key("pay", "REF-ABC")
    assert await was_processed(ik) is False   # first time
    assert await was_processed(ik) is True    # duplicate


@pytest.mark.asyncio
async def test_get_result_returns_stored():
    ik = idempotency_key("pay", "REF-RES")
    await was_processed(ik, result={"txn": "T1"})
    res = await get_result(ik)
    assert res == {"txn": "T1"}


# ────────────────────────────────────────────────────────────────
# Part H: Alert quiet-hours
# ────────────────────────────────────────────────────────────────
def _alert(severity: str = "warning") -> Alert:
    return Alert(name="test_alert", severity=severity, message="boom")


def test_quiet_hours_disabled_by_default(monkeypatch):
    assert AlertManager._in_quiet_hours() is False


def test_quiet_hours_active(monkeypatch):
    monkeypatch.setenv("ALERT_QUIET_HOURS_START", "00:00")
    monkeypatch.setenv("ALERT_QUIET_HOURS_END", "23:59")
    assert AlertManager._in_quiet_hours() is True


def test_quiet_hours_inactive(monkeypatch):
    monkeypatch.setenv("ALERT_QUIET_HOURS_START", "00:00")
    monkeypatch.setenv("ALERT_QUIET_HOURS_END", "00:01")
    assert AlertManager._in_quiet_hours() is False


def test_quiet_hours_crosses_midnight(monkeypatch):
    monkeypatch.setenv("ALERT_QUIET_HOURS_START", "23:00")
    monkeypatch.setenv("ALERT_QUIET_HOURS_END", "05:00")
    am = AlertManager(dry_run=True)
    from datetime import datetime, timezone
    late = datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc)
    early = datetime(2026, 1, 1, 4, 30, tzinfo=timezone.utc)
    noon = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert am._in_quiet_hours(late) is True
    assert am._in_quiet_hours(early) is True
    assert am._in_quiet_hours(noon) is False


def test_quiet_hours_suppresses_noncritical(monkeypatch):
    monkeypatch.setenv("ALERT_QUIET_HOURS_START", "23:00")
    monkeypatch.setenv("ALERT_QUIET_HOURS_END", "05:00")
    sent = []
    am = AlertManager(
        dry_run=False,
        telegram_fn=lambda text, _ctx: sent.append(text) or True,
    )
    am._in_quiet_hours = lambda: True
    assert am.dispatch(_alert("warning")) is True
    assert len(sent) == 0  # suppressed during quiet hours


def test_critical_breaches_quiet_hours(monkeypatch):
    monkeypatch.setenv("ALERT_QUIET_HOURS_START", "23:00")
    monkeypatch.setenv("ALERT_QUIET_HOURS_END", "05:00")
    sent = []
    am = AlertManager(
        dry_run=False,
        telegram_fn=lambda text, _ctx: sent.append(text) or True,
    )
    am._in_quiet_hours = lambda: True
    assert am.dispatch(_alert("critical")) is True
    assert len(sent) == 1  # critical alerts always go through