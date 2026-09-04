"""Tests for the instant booking/order fast path (Phases 2-4)."""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.mark.asyncio
async def test_incomplete_booking_returns_none():
    from services.instant_actions import try_instant_action
    reply, slots = await try_instant_action(
        "919000000001", "I want to book a table", 3, None)
    assert reply is None                 # no date/time -> agent should ask
    assert slots["intent_hint"] == "booking"


@pytest.mark.asyncio
async def test_non_action_message_returns_none():
    from services.instant_actions import try_instant_action
    reply, slots = await try_instant_action(
        "919000000002", "What are your timings?", 3, None)
    assert reply is None
    assert slots["intent_hint"] is None
