"""Broadcast-Lead-Creative-AI tests: A/B rotation, delays, affirmative capture."""
import asyncio

from creative_broadcast import (
    build_creative_message, plan_creative_batch, is_affirmative, LEAD_REPLY,
    TEMPLATE_A, TEMPLATE_B,
)

PROFILE = {
    "business_name": "Smile Dental",
    "vertical": "doctor",
    "brand_voice": "formal",
    "service_name": "AI-Powered Booking Assistant",
    "service_one_liner": "automates chats and books appointments 24/7",
    "key_benefits": ["fill slots faster", "cut admin time", "boost revenue"],
    "cta_text": "Reply YES for a 14-day free trial",
    "cta_link": "https://s.link/14d",
}

CASUAL = {**PROFILE, "brand_voice": "casual"}


def test_template_a_seo():
    m = build_creative_message(PROFILE, "Maya", TEMPLATE_A)
    assert m["text"].startswith("Hi Maya,")
    assert "Smile Dental" in m["text"]
    assert "Reply YES for a 14-day free trial" in m["text"]
    assert len(m["text"]) <= 160


def test_template_b_creative_hook():
    m = build_creative_message(CASUAL, "Ravi", TEMPLATE_B)
    assert m["text"].startswith("Hey Ravi!")
    assert "Reply YES" in m["text"]
    assert len(m["text"]) <= 160


def test_emoji_rules():
    formal = build_creative_message(PROFILE, "x", TEMPLATE_A)["text"]
    casual = build_creative_message(CASUAL, "x", TEMPLATE_B)["text"]
    assert "🚀" not in formal and "🔥" not in formal
    assert any(e in casual for e in ("🚀", "👍", "✨", "🔥"))


def test_rotation_random_and_delays():
    # Spec: rotate_templates=true -> RANDOM A/B pick; delays 2-7s ints;
    # entries carry client_id (spec persistence metadata).
    rows = [{"phone": f"+91900000000{i}", "name": f"P{i}"} for i in range(24)]
    plan = plan_creative_batch(rows, CASUAL, rotate=True, client_id=77)
    tpls = {p["template_id"] for p in plan}
    assert tpls == {"A", "B"}                       # both templates appear
    assert all(2 <= p["delay_seconds"] <= 7 for p in plan)
    assert all(isinstance(p["delay_seconds"], int) for p in plan)
    assert all(p["client_id"] == 77 for p in plan)


def test_rotation_alternate_mode():
    # "alternate" keeps the deterministic A,B,A order (tests/preview).
    rows = [{"phone": f"+91900000000{i}"} for i in range(3)]
    plan = plan_creative_batch(rows, CASUAL, rotate="alternate")
    assert [p["template_id"] for p in plan] == ["A", "B", "A"]


def test_skip_opted_out_and_invalid():
    # Spec resp. 1: opted-out -> SKIP; non-E.164 -> SKIP (never messaged).
    rows = [{"phone": "+919999777777", "name": "Ok", "opted_out": True},
            {"phone": "not-a-number", "name": "Bad"},
            {"phone": "+919999888888", "name": "Good"}]
    plan = plan_creative_batch(rows, CASUAL, rotate="alternate")
    assert plan[0]["action"] == "SKIP" and plan[0]["skip_reason"] == "opted_out"
    assert plan[1]["action"] == "SKIP" and plan[1]["skip_reason"] == "invalid_phone"
    assert "message" in plan[2] and plan[2]["template_id"] == "A"


def test_media_only_on_b_and_casual():
    # Spec resp. 4: image "adds value" heuristic — B/casual only.
    prof = {**CASUAL, "image_url": "https://x.com/b.jpg"}
    rows = [{"phone": "+919999777777"}, {"phone": "+919999666666"}]
    plan = plan_creative_batch(rows, prof, rotate="alternate")
    assert "media" not in plan[0] and "message" in plan[0]   # A -> plain text
    assert plan[1]["media"]["type"] == "image" and \
        plan[1]["media"]["url"].startswith("https://")
    # formal voice never gets media, even on B
    plan_f = plan_creative_batch(rows, {**PROFILE, "image_url": "https://x.com/b.jpg"},
                                 rotate="alternate")
    assert "media" not in plan_f[1] and "message" in plan_f[1]


def test_affirmative_matches():
    for y in ("yes", "YES PLEASE", "I'm interested", "count me in", "sure", "ok"):
        assert is_affirmative(y), y
    assert not is_affirmative("hello")
    assert not is_affirmative("no")
    assert LEAD_REPLY.startswith("Great!")


def test_capture_lead_reply():
    async def _go():
        from db import init_db
        await init_db()
        from db import Client, upsert_contact
        from creative_broadcast import capture_lead_reply
        async with __import__("db").async_session() as session:
            c = Client(business_name="Test", vertical="general",
                       whatsapp_number="+91100000000")
            session.add(c)
            await session.commit()
            await session.refresh(c)
            cid = c.id
        out = await capture_lead_reply(cid, "+919999999999", "yes please")
        assert out.get("reply") and out["source"] == "broadcast"
        async with __import__("db").async_session() as session:
            from db import Contact
            from sqlalchemy import select
            res = (await session.execute(select(Contact).where(
                Contact.client_id == cid))).scalars().all()
            assert any(getattr(x, "source", None) == "broadcast" or x.lead_status == "new"
                       for x in res)
    asyncio.run(_go())