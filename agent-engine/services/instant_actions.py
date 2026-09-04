"""Instant booking/order fast path (Phases 2-4).

Deterministic pipeline that runs BEFORE the LLM agent loop:
  1. Extract slots (Hinglish/English) with services.slot_extractor
  2. If a booking is complete (date+time) -> book + owner alert  (<1s)
  3. If an order has items -> price from catalog + save + owner alert
  4. Unknown phone -> auto-capture lead (Hot/Warm/Cold)
Returns (reply, None) when handled, or (None, slots) to continue to the
LLM agents (e.g. incomplete booking -> concierge asks for the time).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, Optional, Tuple

from business_profiles import business_manager
from business_profiles import Order
from services.slot_extractor import extract_slots
from tools.calendar_tools import book_appointment

logger = logging.getLogger("instant_actions")


def _price_items(items: list, catalog: list, tax_pct: float):
    """Match extracted item names against the business catalog."""
    priced, unmatched, subtotal = [], [], 0.0
    for it in items:
        q = (it.get("name") or "").lower()
        match = None
        for c in catalog:
            cname = (c.get("name") or "").lower()
            if cname and (cname in q or q in cname):
                match = c
                break
        if match:
            line = match.get("price", 0) * it["qty"]
            subtotal += line
            priced.append({"item_id": match.get("id", ""), "name": match.get("name", it["name"]),
                           "qty": it["qty"], "price": match.get("price", 0)})
        else:
            unmatched.append({"name": it["name"], "qty": it["qty"]})
    tax = round(subtotal * tax_pct / 100, 2)
    return priced, unmatched, subtotal, tax


async def _notify_owner(client_id: int, text: str, profile: Optional[dict]):
    """Best-effort WhatsApp alert to the owner (anti-ban queue on bridge side)."""
    try:
        import httpx
        from config import settings
        phone = (profile or {}).get("contact_phone") or ""
        if not phone:
            return
        url = f"{settings.whatsapp_bridge_url.rstrip('/')}/send"
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(url, json={"chat_id": phone if "@" in phone else f"{phone}@c.us",
                                     "message": text})
    except Exception as e:
        logger.warning("owner alert skipped: %s", e)


async def try_instant_action(phone_number: str, message: str, client_id: int,
                             profile: Optional[dict]) -> Tuple[Optional[str], Dict]:
    """Returns (reply, slots). reply is None when the LLM agents should run."""
    from business_profiles import business_manager

    slots = extract_slots(message)
    intent = slots.get("intent_hint")
    if not intent:
        return None, slots

    biz = None
    for bid, p in business_manager.profiles.items():
        if p.client_id == int(client_id):
            biz = bid
            break
    catalog = business_manager.get_catalog(biz) if biz else []
    biz_name = (profile or {}).get("name") or "our business"

    # ── Booking ────────────────────────────────────────────────────────────
    if intent == "booking":
        if not (slots.get("date") and slots.get("time")):
            return None, slots  # incomplete -> let the concierge ask politely
        res = await book_appointment(
            phone_number=phone_number, date=slots["date"], time=slots["time"],
            client_id=client_id,
            title=f"Table/Visit x{slots.get('guests') or 1}",
            notes=f"guests={slots.get('guests') or 1}; raw={message[:120]}")
        if res.get("status") != "success":
            return None, slots  # slot conflict etc -> agent handles gracefully
        when = f"{slots['date']} at {slots['time']}"
        guests = slots.get("guests") or 1
        reply = (f"✅ Booked for {guests} on {when}. "
                 f"Reply here to change or cancel. – {biz_name}")
        await _notify_owner(client_id,
                            f"🔔 New Booking — {guests} guest(s), {when}, "
                            f"ph {phone_number}", profile)
        return reply, slots

    # ── Order ──────────────────────────────────────────────────────────────
    if intent == "order" and slots.get("items"):
        if not biz:
            return None, slots
        tax_pct = float((profile or {}).get("tax_rate_percent") or 0)
        priced, unmatched, subtotal, tax = _price_items(slots["items"], catalog, tax_pct)
        if not priced:
            return None, slots  # nothing matched the menu -> agent answers
        total = round(subtotal + tax, 2)
        order = business_manager.create_order(biz, Order(
            id=uuid.uuid4().hex[:10], business_id=biz, customer_phone=phone_number,
            items=priced, subtotal=round(subtotal, 2), tax_amount=tax, total=total,
            delivery_address=slots.get("address") or "",
            notes=f"raw={message[:120]}"))
        lines = "\n".join(f"• {p['name']} x{p['qty']} — ₹{p['price'] * p['qty']}" for p in priced)
        reply = (f"🛒 Order confirmed!\n{lines}\n"
                 + (f"Tax: ₹{tax}\n" if tax else "")
                 + f"Total: ₹{total}\n"
                 + (f"Delivery to: {slots['address']}\n" if slots.get("address") else "")
                 + f"Payment: cash/UPI on delivery. – {biz_name}")
        await _notify_owner(client_id,
                            f"🛒 New Order ₹{total} from {phone_number}\n"
                            + "\n".join(f"{p['name']} x{p['qty']}" for p in priced)
                            + (f"\nDeliver: {slots['address']}" if slots.get("address") else ""),
                            profile)
        return reply, slots

    return None, slots
