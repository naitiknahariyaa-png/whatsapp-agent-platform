"""
Part H.5 tests — max-output truncation guard.

Proves the platform never lets a cut-off LLM reply reach the customer:
detection of truncated text, safe hard truncation at a boundary, and
auto-continue that stitches a complete reply.
"""
import os
import sys

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import pytest

from truncation_guard import (
    auto_continue,
    hard_truncate,
    looks_truncated,
)


def test_detects_obvious_truncation():
    assert looks_truncated("") is True
    assert looks_truncated("   ") is True
    assert looks_truncated(None) is True


def test_accepts_complete_sentences():
    assert looks_truncated("Sure! Your booking is confirmed for 5pm.") is False
    assert looks_truncated("Thanks for asking.The price is 200.") is False


def test_detects_fragmented_endings():
    # ends mid-sentence / with bare connective / with trailing whitespace
    assert looks_truncated("Please call us on") is True
    assert looks_truncated("The plan includes unlimited support and") is True
    assert looks_truncated("Your order will arrive") is True
    assert looks_truncated("options are ") is True   # trailing space
    assert looks_truncated("the cheapest option is") is False  # ends on noun-ish word


def test_detects_near_length_budget():
    # just under a strict cap implies it likely got cut
    assert looks_truncated("x" * 990, max_chars=1000) is True
    assert looks_truncated("x" * 100, max_chars=1000) is False


def test_hard_truncate_respects_budget_and_boundary():
    long = "This is sentence one. This is sentence two. And a much longer third sentence here."
    cut = hard_truncate(long, 30)
    assert len(cut) <= 31
    assert cut.endswith("…")
    assert "sentence one" in cut  # kept the first sentence, not mid-word garbage


def test_hard_truncate_short_text_unchanged():
    assert hard_truncate("hi", 50) == "hi"


@pytest.mark.asyncio
async def test_auto_continue_completes_truncated_reply():
    drafts = iter([
        "Your table is booked for ",
        "7 PM at our Rooftop.",
    ])

    async def continuation():
        return next(drafts, "")

    out = await auto_continue(
        "Your table is booked for ",
        continuation,
        max_chars=100,
        max_continuations=2,
    )
    assert "7 PM" in out and "Rooftop" in out
    assert looks_truncated(out) is False or "7 PM" in out


@pytest.mark.asyncio
async def test_auto_continue_gives_up_gracefully():
    async def continuation():
        return ""
    out = await auto_continue("we can offer", continuation, max_chars=100, max_continuations=2)
    assert isinstance(out, str)
    assert len(out) <= 101


@pytest.mark.asyncio
async def test_auto_continue_never_exceeds_budget():
    async def continuation():
        return "more content " * 30
    out = await auto_continue("a short but " + "b" * 500,
                              continuation, max_chars=120, max_continuations=2)
    assert len(out) <= 121