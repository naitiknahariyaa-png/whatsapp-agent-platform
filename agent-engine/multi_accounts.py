"""
Terminal Multi-Account Manager - many owners, many accounts, parallel AI.

Each account (Client) has its own business profile (vertical, brand voice,
services/menu, contact list). run_all() launches ONE asyncio worker per
account in parallel; every worker autonomously writes and sends outreach for
its OWN business only - copy is generated strictly from that account's own
profile (never another account's data), with anti-ban pacing.

Modes:
* simulate (default) - full pipeline: per-vertical copy + Message rows,
  but no network. Works even when the WhatsApp channel is blocked; you watch
  every account run automatically in the terminal.
* live - routes each send through Meta Cloud API first, bridge fallback
  (creative_broadcast._send_one). Only fires when a channel actually works;
  stops an account on first channel failure instead of pretending.

Profile file format (JSON list):
[
  {"business_name": "Dr Asha Clinic", "vertical": "doctor",
   "whatsapp_number": "+919000000001", "brand_voice": "formal",
   "services": ["Skin consultation", "Laser therapy"],
   "business_hours": "Mon-Sat 10:00-19:00",
   "contacts": [{"name": "Ramesh", "phone": "+919888777111"}]}
]
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("multi_accounts")

# Global send spacing across ALL account workers (anti-ban on shared channel)
_GLOBAL_SPACING = float(os.getenv("MULTI_ACC_SPACING", "0.25"))
_last_send_ts = 0.0
_spacing_lock = asyncio.Lock()

# Per-vertical value hooks - the AI may only pitch from the account's OWN
# profile (services/menu); these phrases just shape the closing line.
_VERTICAL_HOOK = {
    "doctor": "book your consultation",
    "salon": "book your next makeover",
    "restaurant": "reserve your table",
    "retail": "grab this week's picks",
    "legal": "schedule a consultation",
    "ca": "schedule a consultation",
}


def load_profiles(path: str) -> List[Dict[str, Any]]:
    """Load and validate an owner-profiles JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("accounts", [data])
    return [p for p in data if p.get("business_name")]


async def setup_accounts(path: str) -> Dict[str, Any]:
    """Create one Client (account) per profile. Skips duplicate numbers."""
    from sqlalchemy import select
    from db import async_session, Client
    profiles = load_profiles(path)
    created, skipped = [], []
    async with async_session() as session:
        for p in profiles:
            num = (p.get("whatsapp_number")
                   or f"+9190{random.randint(10000000, 99999999)}").strip()
            existing = (await session.execute(
                select(Client).where(Client.whatsapp_number == num)))\
                .scalar_one_or_none()
            if existing:
                skipped.append({"business_name": p["business_name"],
                                "client_id": existing.id,
                                "reason": "number_exists"})
                continue
            c = Client(business_name=p["business_name"],
                       vertical=p.get("vertical", "general"),
                       whatsapp_number=num, plan=p.get("plan", "trial"),
                       business_profile={
                           "brand_voice": p.get("brand_voice", "casual"),
                           "services": p.get("services", []),
                           "menu": p.get("menu", []),
                           "business_hours": p.get("business_hours", ""),
                           "contacts": p.get("contacts", [])})
            session.add(c)
            await session.flush()
            created.append({"client_id": c.id,
                            "business_name": c.business_name,
                            "vertical": c.vertical, "whatsapp_number": num})
        await session.commit()
    return {"ok": True, "created": created, "skipped": skipped}


async def list_accounts() -> List[Dict[str, Any]]:
    from sqlalchemy import select
    from db import async_session, Client
    async with async_session() as session:
        rows = (await session.execute(
            select(Client).order_by(Client.id))).scalars().all()
        return [{"client_id": c.id, "business_name": c.business_name,
                 "vertical": c.vertical, "whatsapp_number": c.whatsapp_number,
                 "plan": c.plan, "is_active": c.is_active,
                 "contacts": len((c.business_profile or {}).get("contacts", [])),
                 "services": (c.business_profile or {}).get("services", [])[:3]}
                for c in rows]


def build_account_message(profile: Dict[str, Any], contact: Dict[str, Any]) -> str:
    """Per-account AI copy - ONLY this business's own services, <=160 chars.

    Never references another account's data: input is this account's profile
    plus one contact; there is no other account in scope to leak from."""
    nm = (contact.get("name") or "").strip()
    name = nm.split()[0] if nm else "there"
    biz = profile.get("business_name") or "our business"
    services = profile.get("services") or []
    if not services and profile.get("menu"):
        services = [m.get("name", "") for m in profile["menu"]
                    if isinstance(m, dict)]
    svc = services[0] if services else "our services"
    extra = f", {services[1]}" if len(services) > 1 else ""
    hours = profile.get("business_hours") or ""
    hours_txt = f" Open {hours}." if hours and len(hours) < 40 else ""
    hook = _VERTICAL_HOOK.get((profile.get("vertical") or "general").lower(),
                              "get started today")
    variants = [
        f"Hi {name}! {biz}: {svc}{extra}. {hook.capitalize()} this week.",
        f"Hi {name}, {biz} here - {svc}{extra}, done right. "
        f"{hook.capitalize()}!",
        f"Hello {name}, need {svc.lower()}? {biz} has you covered.{hours_txt}",
        f"Hi {name}! {biz}: expert {svc.lower()}{extra}. "
        f"Reply YES to {hook}.",
    ]
    for v in variants:
        if len(v) <= 160:
            return v
    return f"Hi {name}, {biz}: {svc}. Reply YES!"[:160]


async def _paced_send_gap(fast: bool = False) -> None:
    """Space sends across all account workers (shared-channel anti-ban)."""
    global _last_send_ts
    gap = 0.05 if fast else _GLOBAL_SPACING
    async with _spacing_lock:
        since = time.monotonic() - _last_send_ts
        if since < gap:
            await asyncio.sleep(gap - since)
        _last_send_ts = time.monotonic()


async def _account_worker(client: Dict[str, Any], mode: str, limit: int,
                          fast: bool, on_status) -> Dict[str, Any]:
    """One autonomous worker per account: copy -> paced send -> record."""
    from db import async_session, save_message
    cid = client["client_id"]
    profile = client.get("profile") or {}
    contacts = profile.get("contacts") or []
    if limit:
        contacts = contacts[:limit]
    sent = failed = 0
    for i, ct in enumerate(contacts):
        text = build_account_message(profile, ct)
        if mode == "simulate":
            await _paced_send_gap(fast)
            try:
                async with async_session() as session:
                    await save_message(session, phone_number=ct["phone"],
                                       content=text, direction="outgoing",
                                       client_id=cid, status="simulated")
            except Exception as e:
                logger.warning("[!] record failed: %s", e)
            sent += 1
            if on_status:
                await on_status(cid, client["business_name"], i + 1,
                                len(contacts), ct["phone"], "SIM", text)
        else:
            from creative_broadcast import _send_one
            await _paced_send_gap(fast)
            res = await _send_one({"phone": ct["phone"], "message": text},
                                  cid, use_meta=True)
            if res.get("ok"):
                sent += 1
                try:
                    async with async_session() as session:
                        await save_message(session, phone_number=ct["phone"],
                                           content=text, direction="outgoing",
                                           client_id=cid, status="sent")
                except Exception as e:
                    logger.warning("[!] record failed: %s", e)
                if on_status:
                    await on_status(cid, client["business_name"], i + 1,
                                    len(contacts), ct["phone"], "SENT", text)
            else:
                failed += 1
                if on_status:
                    await on_status(cid, client["business_name"], i + 1,
                                    len(contacts), ct["phone"],
                                    f"FAIL: {res.get('error') or 'channel down'}",
                                    text)
                break  # channel down - stop THIS account; others keep running
    return {"client_id": cid, "business_name": client["business_name"],
            "sent": sent, "failed": failed, "total": len(contacts)}


async def run_all(mode: str = "simulate", client_ids: Optional[List[int]] = None,
                  limit: int = 0, fast: bool = False, on_status=None) -> Dict[str, Any]:
    """Launch one worker per account IN PARALLEL and await all of them."""
    from sqlalchemy import select
    from db import async_session, Client
    async with async_session() as session:
        q = select(Client).where(Client.is_active == True)  # noqa: E712
        if client_ids:
            q = q.where(Client.id.in_(client_ids))
        rows = (await session.execute(q.order_by(Client.id))).scalars().all()
    accounts = [{"client_id": c.id, "business_name": c.business_name,
                 "profile": {**(c.business_profile or {}),
                             "business_name": c.business_name,
                             "vertical": c.vertical}}
                for c in rows]
    if not accounts:
        return {"ok": False, "error": "no accounts - run accounts-setup first"}
    results = await asyncio.gather(*[
        _account_worker(a, mode, limit, fast, on_status) for a in accounts])
    return {"ok": all(r["failed"] == 0 for r in results), "mode": mode,
            "accounts": len(results), "results": list(results)}
