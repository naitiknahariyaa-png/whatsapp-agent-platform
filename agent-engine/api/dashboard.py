"""
Minimal server-rendered owner dashboard (FastAPI + Jinja2).

Features:
  - email/password login (HttpOnly JWT cookie, reuses auth.authenticate)
  - client list with is_active toggle
  - drill-down: client -> leads -> message thread
  - "Create Order" button on each lead
  - CSV export buttons (delegates to /api/admin/export)

Access: platform admins see all clients; client-role users only their own.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import Role, authenticate, create_access_token, decode_token
from db import (
    async_session, Client,
    list_leads, get_lead_messages, get_orders, admin_overview, create_order,
)

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))

COOKIE = "wap_dashboard"


def _user_from_cookie(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:
        return None
    return {"user_id": payload.get("sub"), "email": payload.get("email", ""),
            "role": payload.get("role", ""), "client_id": payload.get("client_id")}


def _require_dashboard_user(request: Request) -> dict:
    user = _user_from_cookie(request)
    if not user:
        raise HTTPException(401, "Not logged in")
    return user


def _render(request: Request, view: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"view": view, **ctx}, status_code=status_code)


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    user = _user_from_cookie(request)
    if not user:
        return _render(request, "login")
    if user["role"] == Role.ADMIN.value:
        async with async_session() as session:
            res = await session.execute(Client.__table__.select().order_by(Client.id))
            clients = [dict(m) for m in res.mappings().all()]
        stats = await admin_overview()
    else:
        cid = user.get("client_id")
        if not cid:
            return _render(request, "login", error="No business linked to this account")
        async with async_session() as session:
            res = await session.execute(Client.__table__.select().where(Client.id == cid))
            row = res.mappings().first()
        clients = [dict(row)] if row else []
        stats = None
    return _render(request, "home", user=user, clients=clients, stats=stats)


@router.post("/admin/dashboard/login")
async def dashboard_login(email: str = Form(...), password: str = Form(...)):
    user = await authenticate(email.strip(), password)
    if not user:
        return HTMLResponse("<h3>Invalid email or password</h3>"
                            '<a href="/admin/dashboard">Try again</a>', status_code=401)
    token = create_access_token(user.id, user.email, user.role, user.client_id)
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=24 * 3600)
    return resp


@router.post("/admin/dashboard/logout")
async def dashboard_logout():
    resp = RedirectResponse("/admin/dashboard", status_code=303)
    resp.delete_cookie(COOKIE)
    return resp


# ── Client actions ────────────────────────────────────────────────────────────

@router.post("/admin/dashboard/clients/{client_id}/toggle")
async def dashboard_toggle_client(client_id: int, request: Request):
    user = _require_dashboard_user(request)
    if user["role"] != Role.ADMIN.value and user.get("client_id") != client_id:
        raise HTTPException(403, "Not allowed")
    async with async_session() as session:
        res = await session.execute(Client.__table__.select().where(Client.id == client_id))
        row = res.mappings().first()
        if not row:
            raise HTTPException(404, "Client not found")
        await session.execute(
            Client.__table__.update().where(Client.id == client_id)
            .values(is_active=not bool(row["is_active"])))
        await session.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


# ── Leads drill-down ──────────────────────────────────────────────────────────

@router.get("/admin/dashboard/clients/{client_id}/leads", response_class=HTMLResponse)
async def dashboard_leads(client_id: int, request: Request):
    user = _require_dashboard_user(request)
    if user["role"] != Role.ADMIN.value and user.get("client_id") != client_id:
        raise HTTPException(403, "Not allowed")
    leads = await list_leads(client_id, limit=200)
    orders = await get_orders(client_id, limit=100)
    return _render(request, "leads", user=user, client_id=client_id,
                   leads=leads, orders=orders)


@router.get("/admin/dashboard/leads/{lead_id}/thread", response_class=HTMLResponse)
async def dashboard_thread(lead_id: int, request: Request, client_id: int = 1):
    user = _require_dashboard_user(request)
    if user["role"] != Role.ADMIN.value and user.get("client_id") != client_id:
        raise HTTPException(403, "Not allowed")
    msgs = await get_lead_messages(client_id, lead_id, limit=200)
    lead = next((l for l in await list_leads(client_id, limit=500) if l["id"] == lead_id), None)
    return _render(request, "thread", user=user, client_id=client_id,
                   lead_id=lead_id, lead=lead, messages=msgs)


@router.post("/admin/dashboard/leads/{lead_id}/order")
async def dashboard_create_order(lead_id: int, request: Request,
                                 client_id: int = Form(...), amount: float = Form(...),
                                 description: str = Form("")):
    user = _require_dashboard_user(request)
    if user["role"] != Role.ADMIN.value and user.get("client_id") != client_id:
        raise HTTPException(403, "Not allowed")
    await create_order(client_id, lead_id, amount,
                       description=description or "created via dashboard")
    return RedirectResponse(f"/admin/dashboard/clients/{client_id}/leads", status_code=303)

    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        payload = decode_token(token)
    except Exception:
        return None
    return {"user_id": payload.get("sub"), "email": payload.get("email", ""),
            "role": payload.get("role", ""), "client_id": payload.get("client_id")}


def _require_dashboard_user(request: Request) -> dict:
    user = _user_from_cookie(request)
    if not user:
        raise HTTPException(401, "Not logged in")
    return user


def _render(request: Request, view: str, status_code: int = 200, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"view": view, **ctx}, status_code=status_code)
