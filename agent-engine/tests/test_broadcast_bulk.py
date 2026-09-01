"""
Tests for bulk broadcast: import pipeline (normalize/validate/dedup/opt-out),
safety rails (force threshold, quiet hours), queue-routed sending with
per-send opt-out skip, and resume idempotency.
"""
import os
import pytest
import pytest_asyncio

os.environ.setdefault("BROADCAST_CONFIRM_THRESHOLD", "3")  # small for tests


@pytest_asyncio.fixture
async def engine():
    from broadcast import BroadcastEngine
    from db import init_db
    await init_db()
    return BroadcastEngine(bridge_url="http://127.0.0.1:9")  # unreachable


@pytest.mark.asyncio
async def test_import_validation_and_dedup(engine):
    res = await engine.import_numbers(501, "test_list_a", [
        ("+91 98765 43210", "Ravi"),        # valid, formatted
        ("919876543210", ""),                # duplicate of the first
        ("12345", ""),                       # malformed
        ("not-a-number", ""),                # malformed
        ("918000000001", "Asha"),            # valid
    ], source="csv")
    assert res["imported"] == 2
    assert res["invalid"] == 2
    assert res["duplicates_in_list"] == 1
    assert res["list_total"] == 2


@pytest.mark.asyncio
async def test_import_optout_excluded(engine):
    from outbound_limiter import record_opt_out
    record_opt_out("918000000002")
    res = await engine.import_numbers(502, "test_list_optout", [
        ("918000000002", ""),  # opted out -> excluded at import
        ("918000000003", "Mo"),
    ])
    assert res["imported"] == 1
    assert "918000000002" in (res.get("opted_out_excluded") or [])


@pytest.mark.asyncio
async def test_import_existing_customer_dedup(engine):
    from db import async_session, upsert_contact
    async with async_session() as s:
        await upsert_contact(s, "918000000004", client_id=503, name="Old Customer")
        await s.commit()
    res = await engine.import_numbers(503, "test_list_cust", [
        ("918000000004", ""),  # already a customer -> skipped
        ("918000000005", "New"),
    ])
    assert res["imported"] == 1
    assert res["already_customers"] == 1


@pytest.mark.asyncio
async def test_launch_requires_force_over_threshold(engine):
    entries = [(f"91810000000{i:02d}", "") for i in range(5)]
    await engine.import_numbers(510, "test_list_big", entries)
    res = await engine.launch_campaign(510, "test_list_big", "hello", force=False)
    assert res.get("needs_force") is True
    assert res["count"] == 5


@pytest.mark.asyncio
async def test_send_routed_through_limiter_with_optout_skip(engine, monkeypatch):
    """Campaign sends must go through outbound_limiter.send_whatsapp (the one
    anti-ban pipeline) and must SKIP opted-out recipients at send time."""
    sent_to = []

    async def fake_send_whatsapp(to, message, client_id=1):
        sent_to.append(to)
        return True  # pretend the bridge accepted

    monkeypatch.setattr("outbound_limiter.send_whatsapp", fake_send_whatsapp)

    await engine.import_numbers(520, "test_list_send", [
        ("918200000001", "A"), ("918200000002", "B"),
    ])
    from outbound_limiter import record_opt_out
    record_opt_out("918200000002")  # opts out AFTER import -> must be skipped now

    res = await engine.launch_campaign(520, "test_list_send", "Hi {name}!")
    assert res.get("campaign_id")
    cid = res["campaign_id"]

    import asyncio
    for _ in range(100):
        stats = await engine.campaign_stats(cid)
        if stats["pending"] == 0:
            break
        await asyncio.sleep(0.05)

    stats = await engine.campaign_stats(cid)
    assert stats["sent"] == 1
    assert stats["skipped"] == 1
    assert sent_to == ["918200000001"]  # only the non-opted-out number

    # audit rows exist per recipient
    from broadcast import CampaignSend
    from db import async_session
    from sqlalchemy import select
    async with async_session() as s:
        rows = (await s.execute(
            select(CampaignSend).where(CampaignSend.campaign_id == cid)
        )).scalars().all()
        statuses = {r.phone: r.status for r in rows}
    assert statuses["918200000001"] == "sent"
    assert statuses["918200000002"] == "skipped"


@pytest.mark.asyncio
async def test_resume_never_double_sends(engine, monkeypatch):
    """After a 'crash' (worker gone, rows still pending), resume sends only
    the pending recipients — already-sent numbers are never re-messaged."""
    sent_to = []

    async def fake_send_whatsapp(to, message, client_id=1):
        sent_to.append(to)
        return True

    monkeypatch.setattr("outbound_limiter.send_whatsapp", fake_send_whatsapp)

    await engine.import_numbers(530, "test_list_resume", [
        ("918300000001", ""), ("918300000002", ""),
    ])
    res = await engine.launch_campaign(530, "test_list_resume", "hello")
    cid = res["campaign_id"]

    # Simulate crash: pause (worker stops) then drop the in-memory task handle
    await engine.pause_campaign(cid)
    engine._running_tasks.pop(cid, None)
    sent_to.clear()

    resumed = await engine.resume_campaign(cid)
    assert resumed["status"] == "resumed"
    import asyncio
    for _ in range(100):
        stats = await engine.campaign_stats(cid)
        if stats["pending"] == 0 and stats["status"] == "completed":
            break
        await asyncio.sleep(0.05)

    # each phone must have exactly ONE successful send row across both runs
    from broadcast import CampaignSend
    from db import async_session
    from sqlalchemy import select, func
    async with async_session() as s:
        rows = (await s.execute(
            select(CampaignSend.phone, func.count(CampaignSend.id))
            .where(CampaignSend.campaign_id == cid,
                   CampaignSend.status == "sent")
            .group_by(CampaignSend.phone)
        )).all()
    per_phone = dict(rows)
    assert all(v == 1 for v in per_phone.values()), per_phone
    assert len(per_phone) == 2


@pytest.mark.asyncio
async def test_quiet_hours_block(engine, monkeypatch):
    monkeypatch.setenv("BROADCAST_QUIET_START", "00:00")
    monkeypatch.setenv("BROADCAST_QUIET_END", "23:59")
    await engine.import_numbers(540, "test_list_quiet", [("918400000001", "")])
    res = await engine.launch_campaign(540, "test_list_quiet", "hi")
    assert "Quiet hours" in res.get("error", "")
    res2 = await engine.launch_campaign(540, "test_list_quiet", "hi",
                                        ignore_quiet_hours=True)
    assert res2.get("campaign_id")
