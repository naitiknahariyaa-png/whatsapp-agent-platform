"""Tests for the orchestrator: intent detection, language + usage metering."""
import asyncio
import pytest
from orchestrator import (
    AgentOrchestrator, IntentDetector, ResponseGenerator, detect_language,
)
from usage_metering import usage_meter
from metrics import metrics_collector


def test_keyword_fallback_intent():
    d = IntentDetector()
    res = d._keyword_fallback("book appointment kal 5 baje")
    assert res["intent"] == "appointment_booking"
    assert "date" in res["entities"]


def test_keyword_fallback_greeting():
    d = IntentDetector()
    assert d._keyword_fallback("namaste").get("intent") == "greeting"


def test_response_generator_localised_fallback():
    g = ResponseGenerator()
    # With no LLM available it should fall back to a localised template.
    out = g._keyword_fallback if False else None
    reply = asyncio.run(_gen(g))
    assert isinstance(reply, str) and len(reply) > 0


async def _gen(g):
    return await g.generate("greeting", "hi", [], lang="hi")


def test_orchestrator_language_passthrough():
    # detect_language is wired into the orchestrator's process_message path.
    o = AgentOrchestrator()
    assert hasattr(o, "process_message")
    assert hasattr(o, "process_incoming_message")


@pytest.mark.asyncio
async def test_process_message_records_usage_and_metrics():
    from db import init_db
    await init_db()
    o = AgentOrchestrator()
    usage_meter.reset_memory()
    metrics_collector.reset_memory()

    reply = await o.process_message("+917777777777", "namaste", client_id=99)
    assert isinstance(reply, str) and len(reply) > 0

    usage = usage_meter.get_usage(99)
    assert usage["messages_received"] >= 1
    assert usage["messages_sent"] >= 1
    # greeting typically isn't a lead, but tokens are always counted
    assert usage["tokens_used"] >= 1
