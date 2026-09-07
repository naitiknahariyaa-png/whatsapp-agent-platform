"""Report broadcast: xlsx/csv loading, rules ladder, <=160 guarantee."""
import asyncio

from report_broadcast import (
    build_all, build_outreach_message, load_report, normalize_phone,
)

REPORT = r"E:\business\Meerut_Business_Contacts (1).xlsx"


def test_load_real_report():
    rows = load_report(REPORT)
    assert len(rows) == 26
    first = rows[0]
    assert first["business_name"] == "Om Big Brands"
    assert first["phone"] == "+91 82734 00929"
    assert first["category"] == "shops"


def test_build_all_generates_all_valid():
    rows = load_report(REPORT)
    msgs = build_all(rows, brand_voice="playful")
    assert len(msgs) == 26
    assert all(m["valid"] for m in msgs)
    assert all(m["chars"] <= 160 for m in msgs)
    assert all(m["phone"].startswith("+91") for m in msgs)
    # every message keeps the required line and the CTA
    for m in msgs:
        assert "Unlock AI-powered WhatsApp automation for your business" in m["text"]
        assert "Reply YES for a free demo!" in m["text"]
    # personalization: short names get a name-greeting
    by_name = {m["business_name"]: m for m in msgs}
    assert by_name["Om Big Brands"]["text"].startswith("Hi Om Big Brands!")
    # very long names degrade to "Hi there!" to stay within 160
    long_one = by_name["Dr Shishir/Ruchika/S.K Gupta (Skin, Laser & Hair)"]
    assert long_one["text"].startswith("Hi there!")


def test_formal_voice_no_emoji():
    out = build_outreach_message("Om Big Brands", "shops", brand_voice="formal")
    assert "✨" not in out["text"]


def test_phone_normalization():
    assert normalize_phone("+91 82734 00929") == "+918273400929"
    assert normalize_phone("9837071049") == "+919837071049"
    assert normalize_phone("0121 712 7800") == "+911217127800"
    assert normalize_phone("") is None
    assert normalize_phone("123") is None


def test_duplicate_rows_marked():
    rows = [{"category": "shops", "business_name": "A", "phone": "+91 90000 00001"},
            {"category": "shops", "business_name": "B", "phone": "+91 90000 00001"}]
    msgs = build_all(rows)
    assert msgs[0]["valid"] is True
    assert msgs[1]["valid"] is False and "duplicate" in msgs[1]["reason"]
