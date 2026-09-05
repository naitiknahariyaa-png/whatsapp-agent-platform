"""
Lead Visibility + Order Processing + Multi-Tenant Admin API.

Tenant-safe: every lead/order query is scoped by client_id (and admin
endpoints require the admin role). Mounted at /api.
"""
from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import Role, require_admin, require_role, get_current_user, User
from db import (
    Client, Contact,
    list_leads, get_lead_messages, update_lead_status,
    create_order, get_orders, admin_overview,
)

router = APIRouter()


# ── helpers ────────────────────────────────────────────────────────────────────

def _my_client_id(user: User) -> int:
    """Client admins see their own tenant; platform admins pass client_id explicitly."""
    if Role(user.role) == Role.ADMIN and user.client_id is None:
        return -1  # signal: admin context, resolve per-request
    return user.client_id or 1


# ── Schemas ───────────────────────────────────────────────────────────────────

class OrderIn(BaseModel):
    amount: float
    currency: str = "INR"
    description: str = ""
    notes: str = ""


# ── Lead Visibility ───────────────────────────────────────────────────────────

@router.get("/clients/{client_id}/leads")
async def get_leads(
    client_id: int,
    status: str = Query("", description="new|contacted|qualified|won|lost"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_role(Role.CLIENT, Role.ADMIN)),
):
    """Paginated leads for a shop. Clients are locked to their own client_id."""
    if Role(user.role) != Role.ADMIN and user.client_id != client_id:
        raise HTTPException(403, "Not your business")
    rows = await list_leads(client_id, status=status, limit=limit, offset=offset)
    return {"client_id": client_id, "count": len(rows), "leads": rows}


@router.get("/clients/{client_id}/leads/{lead_id}/messages")
async def get_lead_messages_route(
    client_id: int, lead_id: int,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_role(Role.CLIENT, Role.ADMIN)),
):
    """Full WhatsApp message thread for one lead."""
    if Role(user.role) != Role.ADMIN and user.client_id != client_id:
        raise HTTPException(403, "Not your business")
    msgs = await get_lead_messages(client_id, lead_id, limit=limit)
    return {"client_id": client_id, "lead_id": lead_id, "count": len(msgs), "messages": msgs}


@router.patch("/clients/{client_id}/leads/{lead_id}/status")
async def patch_lead_status(
    client_id: int, lead_id: int, body: dict,
    user: User = Depends(require_role(Role.CLIENT, Role.ADMIN)),
):
    """Mark a lead: new/contacted/qualified/won/lost."""
    if Role(user.role) != Role.ADMIN and user.client_id != client_id:
        raise HTTPException(403, "Not your business")
    status = (body.get("status") or "").strip()
    contact = await update_lead_status(client_id, lead_id, status)
    if not contact:
        raise HTTPException(404, "Lead not found")
    return {"status": "ok", "lead_id": lead_id, "lead_status": contact.lead_status}


# ── Order Processing ──────────────────────────────────────────────────────────

@router.post("/clients/{client_id}/leads/{lead_id}/order")
async def post_order(
    client_id: int, lead_id: int, body: OrderIn,
    user: User = Depends(require_role(Role.CLIENT, Role.ADMIN)),
):
    """Convert a lead into an order/sale."""
    if Role(user.role) != Role.ADMIN and user.client_id != client_id:
        raise HTTPException(403, "Not your business")
    order = await create_order(
        client_id, lead_id, amount=body.amount, currency=body.currency,
        description=body.description, notes=body.notes)
    return {"status": "created", "order": order.to_dict()}


@router.get("/clients/{client_id}/orders")
async def get_orders_route(
    client_id: int, status: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(require_role(Role.CLIENT, Role.ADMIN)),
):
    if Role(user.role) != Role.ADMIN and user.client_id != client_id:
        raise HTTPException(403, "Not your business")
    return {"client_id": client_id, "orders": await get_orders(client_id, status=status, limit=limit)}


# ── Multi-Tenant Admin Dashboard ──────────────────────────────────────────────

@router.get("/admin/overview")
async def get_admin_overview(user: User = Depends(require_admin)):
    """Platform-wide stats (admin only)."""
    return await admin_overview()


@router.get("/admin/export")
async def admin_export(
    user: User = Depends(require_admin),
):
    """CSV export of all leads (admin only)."""
    from db import async_session, Contact
    from sqlalchemy import select
    async with async_session() as session:
        rows = (await session.execute(select(Contact).limit(5000))).scalars().all()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["id", "client_id", "name", "phone_hash", "lead_status", "source", "lead_score", "created_at"])
    for c in rows:
        w.writerow([c.id, c.client_id, c.name or "", c.phone_hash or "", c.lead_status or "",
                     c.source or "", c.lead_score, c.created_at.isoformat() if c.created_at else ""])
    return StreamingResponse(io.BytesIO(out.getvalue().encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=leads.csv"})


# ── Onboarding / Custom Agent Training (Section 4) ────────────────────────────

@router.patch("/api/admin/clients/{client_id}/profile")
async def patch_client_profile(client_id: int, body: dict, user: User = Depends(require_admin)):
    """Store the uploaded business profile JSON in Client.business_profile (admin/wizard)."""
    from db import async_session, Client
    from sqlalchemy import select
    async with async_session() as session:
        res = await session.execute(select(Client).where(Client.id == client_id))
        client = res.scalar_one_or_none()
        if not client:
            raise HTTPException(404, "Client not found")
        existing = client.business_profile or {}
        if isinstance(existing, dict) and isinstance(body, dict):
            existing.update(body)
        else:
            existing = body
        client.business_profile = existing
        await session.commit()
        return {"status": "ok", "client_id": client_id,
                "keys": list(client.business_profile.keys())}


@router.patch("/api/me/profile")
async def patch_my_profile(body: dict, user: User = Depends(get_current_user)):
    """Owner updates their own business profile (onboarding wizard step)."""
    from db import async_session, Client
    from sqlalchemy import select
    cid = user.client_id
    if not cid:
        raise HTTPException(400, "No business linked to this account")
    async with async_session() as session:
        res = await session.execute(select(Client).where(Client.id == cid))
        client = res.scalar_one_or_none()
        if not client:
            raise HTTPException(404, "Client not found")
        existing = client.business_profile or {}
        if isinstance(existing, dict) and isinstance(body, dict):
            existing.update(body)
        else:
            existing = body
        client.business_profile = existing
        await session.commit()
        return {"status": "ok", "client_id": cid, "keys": list(client.business_profile.keys())}


