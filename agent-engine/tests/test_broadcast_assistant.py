"""Broadcast-Assistant-AI: copy generation, 160-char limit, image allowlist."""
from broadcast_assistant import (
    MAX_LEN, _fallback_copy, _image_url, build_broadcast_prompt,
    generate_broadcast_copy,
)

PROFILE = {
    "business_name": "GrowFast Agency",
    "vertical": "agency",
    "brand_voice": "playful",
    "service_summary": "AI-driven lead generation",
    "image_url": "https://cdn.growfast.com/banner.jpg",
    "cta_text": "Reply YES to claim a free 30-min strategy call",
    "cta_link": "https://growfast.com/audit",
}

CONTACT = {"name": "Riya", "tags": {"segment": "high-value"}}


def test_prompt_contains_rules():
    p = build_broadcast_prompt(PROFILE, CONTACT)
    assert "160" in p and "playful" in p
    assert "Riya" in p and "high-value" in p
    assert "NEVER mention" in p            # privacy rule
    assert "Reply YES to claim" in p        # CTA
    assert "image will be attached separately" in p


def test_prompt_no_image_when_absent():
    p = build_broadcast_prompt({**PROFILE, "image_url": ""}, CONTACT)
    assert "No image is attached" in p


def test_image_url_allowlist():
    assert _image_url(PROFILE) == "https://cdn.growfast.com/banner.jpg"
    assert _image_url({**PROFILE, "image_url": "http://x.com/b.jpg"}) is None
    assert _image_url({}) is None


def test_fallback_copy_shape():
    out = _fallback_copy(PROFILE, CONTACT)
    assert len(out["text"]) <= MAX_LEN
    assert "Riya" in out["text"]
    assert "Reply YES" in out["text"]
    assert out["image_url"] == "https://cdn.growfast.com/banner.jpg"


def test_fallback_copy_no_name():
    out = _fallback_copy(PROFILE, {"name": "", "tags": {}})
    assert "{{name}}" in out["text"]  # engine substitutes per recipient


def test_fallback_copy_formal_no_link_bloat():
    out = _fallback_copy({**PROFILE, "brand_voice": "formal"},
                         {"name": "Mr Rao", "tags": {}})
    assert out["text"].startswith("Hello Mr Rao")


def test_generate_falls_back_when_llm_offline():
    # llm_setup is not configured in tests -> deterministic fallback
    out = _run(PROFILE, CONTACT)
    assert out["source"] == "fallback"
    assert len(out["text"]) <= MAX_LEN


def _run(profile, contact):
    import asyncio
    from unittest.mock import patch

    class Boom:
        async def ainvoke(self, *a, **k):
            raise RuntimeError("no llm in tests")

    with patch("llm_setup.get_llm", return_value=Boom()):
        return asyncio.run(generate_broadcast_copy(profile, contact))


def test_generate_rejects_overlong_llm_output():
    import asyncio
    from unittest.mock import patch

    class Long:
        async def ainvoke(self, *a, **k):
            class R:
                content = '{"text": "' + "x" * 400 + '"}'
            return R()

    with patch("llm_setup.get_llm", return_value=Long()):
        out = asyncio.run(generate_broadcast_copy(PROFILE, CONTACT))
    assert out["source"] == "fallback"           # 400 chars -> fallback
    assert len(out["text"]) <= MAX_LEN


def test_generate_accepts_valid_llm_output():
    import asyncio
    import json
    from unittest.mock import patch

    good = {"text": "Hey {{name}}! AI leads on autopilot. Reply YES for a free call."}
    class Ok:
        async def ainvoke(self, *a, **k):
            class R:
                content = json.dumps(good)
            return R()

    with patch("llm_setup.get_llm", return_value=Ok()):
        out = asyncio.run(generate_broadcast_copy(PROFILE, CONTACT))
    assert out["source"] == "ai"
    assert out["text"] == good["text"]
    assert out["image_url"] == "https://cdn.growfast.com/banner.jpg"
