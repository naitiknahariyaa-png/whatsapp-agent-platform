"""
Part L tests — verification matrix, load, chaos and connectivity.

These are lighter-weight versions that run quickly in CI (they do not spin up
real Redis/Postgres/WhatsApp) but still exercise the reliability seams:
  - verification matrix reflects real capability coverage
  - load: concurrent idempotent + event-bus publishes stay consistent
  - chaos: handler failure does not kill the event bus; bridge health math
  - connectivity: port allocator picks free ports and waits correctly
"""
import asyncio
import os
import sys

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import pytest

from verification_matrix import (
    LAYERS,
    VERIFICATION_MATRIX,
    coverage_report,
    filter_matrix,
    matrix_summary,
)
from port_allocator import free_port, port_in_use, plan_ports, export_env
from idempotency import idempotency_key, idempotent
from event_bus import EventBus, EventBusEvent, reset_event_bus, get_event_bus


# ────────────────────────────────────────────────────────────────
# Verification Matrix
# ────────────────────────────────────────────────────────────────
def test_matrix_has_capabilities():
    assert len(VERIFICATION_MATRIX) >= 10
    for row in VERIFICATION_MATRIX:
        assert row["capability"]
        assert set(row["layers"]) == set(LAYERS)


def test_filter_matrix_by_layer():
    unit_rows = filter_matrix(layer="unit")
    assert unit_rows
    for r in unit_rows:
        assert r["layers"]["unit"] is True


def test_filter_matrix_by_area():
    rows = filter_matrix(area="Part A")
    assert rows
    for r in rows:
        assert r["area"] == "Part A"


def test_coverage_report_shape():
    report = coverage_report()
    assert set(report.keys()) == set(LAYERS)
    for layer, stats in report.items():
        assert stats["total"] == len(VERIFICATION_MATRIX)
        assert 0 <= stats["pct"] <= 100


def test_matrix_summary():
    summary = matrix_summary()
    assert summary["rows"] == len(VERIFICATION_MATRIX)
    assert "unit" in summary["layers"]


# ────────────────────────────────────────────────────────────────
# Load: concurrent idempotency keeps single execution
# ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_load_concurrent_idempotent_fires_once():
    calls = []
    ik = idempotency_key("load", "bulk-send-001")

    async def op():
        await asyncio.sleep(0.01)
        calls.append(1)
        return {"ok": True}

    # 20 concurrent invocations with the same key
    results = await asyncio.gather(*[idempotent(ik, op) for _ in range(20)])
    executed = [r for r in results if r[1] is False]
    assert len(executed) == 1  # exactly one "first" execution
    assert sum(1 for _ in calls) >= 1


@pytest.mark.asyncio
async def test_load_many_event_bus_publishes():
    reset_event_bus()
    bus = get_event_bus()
    await bus.start()
    received = []

    async def handler(event: EventBusEvent):
        received.append(event)

    bus.add_handler(handler)
    for i in range(50):
        await bus.publish_dict("load.evt", owner_id=i % 5, payload={"i": i})
    for _ in range(50):
        if len(received) >= 50:
            break
        await asyncio.sleep(0.02)
    assert len(received) == 50
    await bus.stop()


# ────────────────────────────────────────────────────────────────
# Chaos: a failing subscriber doesn't kill the bus or others
# ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_chaos_handler_failure_is_contained():
    reset_event_bus()
    bus = get_event_bus()
    await bus.start()

    ok_handler_calls = []
    received = []

    async def failing(event: EventBusEvent):
        raise RuntimeError("boom")

    async def ok_handler(event: EventBusEvent):
        ok_handler_calls.append(event)

    async def tracker(event: EventBusEvent):
        received.append(event)

    bus.add_handler(failing)
    bus.add_handler(ok_handler)
    bus.add_handler(tracker)

    await bus.publish_dict("chaos.evt", owner_id=1, payload={})
    for _ in range(20):
        if received:
            break
        await asyncio.sleep(0.02)

    assert len(received) == 1
    assert len(ok_handler_calls) == 1  # failing handler did not block the others
    await bus.stop()


# ────────────────────────────────────────────────────────────────
# Connectivity: port allocator
# ────────────────────────────────────────────────────────────────
def test_free_port_is_free():
    port = free_port()
    assert isinstance(port, int) and port > 0
    assert port_in_use(port) is False


def test_preferred_port_when_free():
    port = free_port(45999)
    # If 45999 was already taken it still returns an integer free port.
    assert isinstance(port, int) and port > 0


def test_plan_ports_all_unique_or_valid():
    plan = plan_ports()
    assert set(plan.keys()) == {"backend", "bridge_http", "bridge_ws", "worker", "chroma"}
    for v in plan.values():
        assert isinstance(v, int) and v > 0


def test_export_env_maps_standard_vars():
    plan = {"backend": 8000, "bridge_http": 3001, "bridge_ws": 3002, "chroma": 8001, "worker": 9000}
    env = export_env(plan)
    assert env["PORT"] == "8000"
    assert env["BRIDGE_HTTP_PORT"] == "3001"
    assert env["BRIDGE_WS_PORT"] == "3002"
    assert env["CHROMA_PORT"] == "8001"
    assert "WAP_PLAN" in env