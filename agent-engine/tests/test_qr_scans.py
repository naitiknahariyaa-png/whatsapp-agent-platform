"""QR-code scan tracking: token security, rate limiting, DB helpers."""
import asyncio
import time

import jwt as pyjwt
import pytest
from fastapi import HTTPException

import db
from api.qr import (
    _rate_limited, _verify_qr_token, mint_qr_token, recent_scans,
)


# ── Token security ───────────────────────────────────────────────────────────
def test_mint_and_verify_token_roundtrip():
    token = mint_qr_token(7, "counter", "poster", ttl_days=1)
    claims = _verify_qr_token(token)
    assert claims["client_id"] == 7
    assert claims["tag"] == "counter"
    assert claims["source"] == "poster"


def test_tampered_token_rejected():
    token = mint_qr_token(7, "counter")
    # flip the payload
    head, body, sig = token.split(".")
    with pytest.raises(HTTPException) as exc:
        _verify_qr_token(f"{head}.{body[:-2]}AA.{sig}")
    assert exc.value.status_code == 400


def test_expired_token_rejected():
    from auth import JWT_SECRET
    expired = pyjwt.encode(
        {"client_id": 1, "tag": "t", "exp": int(time.time()) - 10},
        JWT_SECRET, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        _verify_qr_token(expired)
    assert exc.value.status_code == 400
    assert "expired" in str(exc.value.detail).lower()


def test_garbage_token_rejected():
    with pytest.raises(HTTPException):
        _verify_qr_token("not.a.token")


# ── Rate limiting ────────────────────────────────────────────────────────────
def test_rate_limiter_blocks_after_limit():
    key = f"test-{time.time()}"
    for _ in range(30):
        assert _rate_limited(key) is False
    assert _rate_limited(key) is True  # 31st within window -> blocked
    assert _rate_limited(key) is True


# ── DB helpers (hermetic sqlite from conftest) ───────────────────────────────
def test_create_qr_scan_and_report():
    async def _flow():
        await db.init_db()
        client = db.Client(business_name="QR Cafe", whatsapp_number="+919000000009")
        async with db.async_session() as session:
            session.add(client)
            await session.commit()
            await session.refresh(client)
            cid = client.id
        scan = await db.create_qr_scan(cid, "counter", source="poster",
                                       ip_hash="abc", user_agent="UA/1.0")
        assert scan.id and scan.tag == "counter"
        assert scan.to_dict()["source"] == "poster"

        rep = await db.qr_report(cid, days=30)
        assert rep["total"] == 1
        assert rep["by_tag"] == {"counter": 1}
        assert rep["recent"][0]["tag"] == "counter"

        # default-enabled flag + explicit disable via column
        assert await db.qr_tracking_enabled(cid) is True
        async with db.async_session() as session:
            c = await session.get(db.Client, cid)
            c.qr_tracking_enabled = False
            await session.commit()
        assert await db.qr_tracking_enabled(cid) is False
        return cid

    asyncio.run(_flow())


def test_in_memory_session_cache():
    from api.qr import _RECENT
    _RECENT[999].append({"tag": "x"})
    assert recent_scans(999) == [{"tag": "x"}]
    _RECENT[999].clear()
