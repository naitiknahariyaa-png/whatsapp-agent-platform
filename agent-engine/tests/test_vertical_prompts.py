"""Per-vertical Sales-Assistant guidelines + media allowlist in prompts."""
from prompt_builder import (
    _media_fields_block, _vertical_guidelines,
    build_advanced_system_prompt, build_system_prompt,
)


def test_vertical_guidelines_doctor():
    g = _vertical_guidelines("doctor", {})
    assert "consultation" in g and "appointment" in g and "prescription" in g
    assert "welcome_image_url" in g  # clinic image source


def test_vertical_guidelines_salon():
    g = _vertical_guidelines("salon", {})
    assert "styling package" in g and "book your makeover" in g
    assert "gallery_images" in g


def test_vertical_guidelines_legal_no_emoji():
    g = _vertical_guidelines("lawyer", {})
    assert "consultation fee" in g and "court date" in g and "NO emojis" in g


def test_vertical_guidelines_generic_uses_brand_voice():
    g = _vertical_guidelines("agency", {"brand_voice": "playful"})
    assert "playful" in g


def test_media_fields_block_allowlist():
    # no media -> explicit do-not-send
    assert "Do NOT send" in _media_fields_block({})
    # single URL passes through
    block = _media_fields_block({"welcome_image_url": "https://cdn.clinic.com/x.jpg"})
    assert "https://cdn.clinic.com/x.jpg" in block and "ONLY these URLs" in block
    # list of product images passes through
    block = _media_fields_block({"product_images": ["https://a.com/p1.jpg", "https://a.com/p2.jpg"]})
    assert "https://a.com/p1.jpg" in block and "https://a.com/p2.jpg" in block
    # non-https entries are dropped from the allowlist
    block = _media_fields_block({"logo_url": "http://insecure.com/l.png"})
    assert "insecure.com" not in block and "Do NOT send" in block


def test_advanced_prompt_includes_vertical_and_template():
    prompt = build_advanced_system_prompt({
        "business_name": "Dr Sharma Clinic",
        "industry": "clinic / doctor's practice",
        "welcome_image_url": "https://cdn.clinic.com/tour.jpg",
    })
    assert "VERTICAL GUIDELINES" in prompt
    assert "OUTBOUND MESSAGE TEMPLATE" in prompt
    assert "https://cdn.clinic.com/tour.jpg" in prompt
    assert "ANTI-HALLUCINATION" in prompt  # guardrails preserved


def test_raw_profile_prompt_includes_vertical_and_media():
    prompt = build_system_prompt({
        "menu": [{"name": "Cut", "price": 300}],
        "brand_voice": "upbeat",
        "vertical": "salon",
        "gallery_images": ["https://cdn.salon.com/before-after.jpg"],
    })
    assert "VERTICAL GUIDELINES — SALON" in prompt
    assert "https://cdn.salon.com/before-after.jpg" in prompt
    assert "OUTBOUND MESSAGE TEMPLATE" in prompt
    assert "ANTI-HALLUCINATION" in prompt
