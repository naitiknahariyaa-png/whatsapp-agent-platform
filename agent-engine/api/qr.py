"""
QR-code scan tracking API.

- POST /api/qr/scan        : PUBLIC. Records a scan of a signed QR token,
                             caches it in an in-memory session, publishes an
                             EventBus event AND pushes it to the owner's live
                             dashboard via the WebSocket ConnectionManager.
- POST /api/qr/codes       : AUTH. Mint signed QR tokens for a tag/placement.
- GET  /api/qr/report      : AUTH. Aggregated scan report (per tag / per day).
- PATCH /api/qr/toggle     : AUTH. Per-client enable/disable flag.

Security: scan tokens are HS256 JWTs signed with the platform JWT secret
({client_id, tag, source?, exp}) so scans cannot be forged for other tenants.
Public endpoint is rate-limited per IP-hash.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from typing import Optional, Dict, Deque, List

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import JWT_SECRET, JWT_ALGORITHM, get_current_user, User, Role
from db import (
    create_qr_scan, qr_report as db_qr_report, qr_tracking_enabled,
)

router = APIRouter()

# ── In-memory session cache of the most recent scans per client ──────────────
_RECENT: Dict[int, Deque[dict]] = defaultdict(lambda: deque(maxlen=100))


def recent_scans(client_id: int) -> List[dict]:
    return list(_RECENT.get(client_id, []))


# ── Rate limiting (simple fixed-window, per IP hash) ─────────────────────────
_RATE: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT = 30          # scans per window per client IP
_RATE_WINDOW = 60.0       # seconds


def _rate_limited(key: str) -> bool:
    now = time.time()
    hits = [t for t in _RATE.get(key, []) if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_LIMIT:
        _RATE[key] = hits
        return True
    hits.append(now)
    _RATE[key] = hits
    return False


def _ip_hash(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        ip = fwd.split(",")[0].strip()
    return hashlib.sha256(f"qr:{ip}".encode()).hexdigest()[:32]


# ── Schemas ──────────────────────────────────────────────────────────────────
class ScanIn(BaseModel):
    token: str          # signed QR JWT
    user_agent: str = ""


class CodeIn(BaseModel):
    tag: str
    source: str = ""
    ttl_days: int = 365


class ToggleIn(BaseModel):
    enabled: bool


def mint_qr_token(client_id: int, tag: str, source: str = "",
                  ttl_days: int = 365) -> str:
    """Create a signed, expiring QR payload (server-side helper / API)."""
    payload = {
        "client_id": int(client_id), "tag": tag, "source": source,
        "iat": int(time.time()), "exp": int(time.time()) + ttl_days * 86400,
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _verify_qr_token(token: str) -> dict:
    try:
        return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(400, "QR code has expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(400, "Invalid QR code")


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.post("/api/qr/scan")
async def record_scan(body: ScanIn, request: Request):
    """PUBLIC: record a QR scan from a signed token."""
    iph = _ip_hash(request)
    if _rate_limited(iph):
        raise HTTPException(429, "Too many scan requests; slow down")

    claims = _verify_qr_token(body.token)
    client_id = int(claims["client_id"])
    tag = str(claims.get("tag", "default"))

    if not await qr_tracking_enabled(client_id):
        return {"status": "ignored", "reason": "qr tracking disabled"}

    scan = await create_qr_scan(
        client_id=client_id, tag=tag, source=str(claims.get("source", "")),
        ip_hash=iph, user_agent=body.user_agent)

    payload = {**scan.to_dict(), "type": "qr_scan"}
    # 1. in-memory session
    _RECENT[client_id].append(payload)
    # 2. central EventBus (reporting, workers, dashboards)
    try:
        from event_bus import get_event_bus
        await get_event_bus().publish_dict(
            "qr_scan_recorded", owner_id=client_id,
            payload={k: v for k, v in payload.items() if k != "type"})
    except Exception:
        pass
    # 3. live WebSocket push to owner dashboard
    try:
        from main import manager
        await manager.broadcast(client_id, payload)
    except Exception:
        pass
    return {"status": "recorded", "scan_id": scan.id, "tag": tag}


@router.post("/api/qr/codes")
async def create_code(body: CodeIn, user: User = Depends(get_current_user)):
    """AUTH: mint a signed QR token for a placement (e.g. tag='counter', source='poster')."""
    if Role(user.role) != Role.ADMIN and user.client_id is None:
        raise HTTPException(403, "No tenant bound to this account")
    client_id = user.client_id or 1
    return {"client_id": client_id, "tag": body.tag, "source": body.source,
            "token": mint_qr_token(client_id, body.tag, body.source, body.ttl_days)}


@router.get("/api/qr/report")
async def report(days: int = 30, client_id: Optional[int] = None,
                 user: User = Depends(get_current_user)):
    """AUTH: aggregated QR-scan report. Platform admins must pass client_id."""
    if Role(user.role) == Role.ADMIN:
        if client_id is None:
            raise HTTPException(400, "client_id required for platform admins")
        cid = client_id
    else:
        cid = user.client_id or 1
        if client_id not in (None, cid):
            raise HTTPException(403, "Cannot view another tenant's report")
    out = await db_qr_report(cid, days=max(1, min(days, 365)))
    out["recent_scans"] = recent_scans(cid)
    return out


@router.patch("/api/qr/toggle")
async def toggle(body: ToggleIn, user: User = Depends(get_current_user)):
    """AUTH: enable/disable QR tracking for the caller's client."""
    from db import async_session, Client
    cid = user.client_id or 1
    async with async_session() as session:
        res = await session.get(Client, cid)
        if not res:
            raise HTTPException(404, "Client not found")
        res.qr_tracking_enabled = body.enabled
        await session.commit()
    return {"client_id": cid, "qr_tracking_enabled": body.enabled}