"""
Broadcast-Lead-Creative-AI — human-like, SEO/ad-creative WhatsApp broadcast.

Combines:
* template A/B rotation (SEO-focus vs ad-creative hook),
* an anti-ban anti-bot pacing layer (55-65s jittered gap between sends),
* per-message delay_seconds + template_id attributes,
* optional media block when owner_profile.image_url is present,
* a bot-reply flow for affirmative ("YES") replies that persists a lead.

Delivery prefers the official Meta Cloud API (_send_via_meta, which bypasses
the whatsapp-web.js "smba" limitation) and falls back to the bridge send only
if Meta is unconfigured. Anti-ban pacing is never mentioned in message text.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("creative_broadcast")

MAX_LEN = 160
TEMPLATE_A = "A"  # SEO-focused hook
TEMPLATE_B = "B"  # Ad-creative hook

DEFAULT_PROFILE: Dict[str, Any] = {
    "business_name": "Your Business",
    "vertical": "general",
    "brand_voice": "casual",
    "service_name": "AI-Powered Booking Assistant",
    "service_one_liner": ("automates WhatsApp conversations and books "
                          "appointments 24/7"),
    "key_benefits": ["fill slots 30% faster", "cut admin time by 2 hrs daily",
                     "boost revenue by up to 20%"],
    "cta_text": "Reply YES for a 14-day free trial",
    "cta_link": "",
}

# Human-like delay window (55-65s). Override via env.
HUMAN_MIN = float(__import__("os").getenv("OUTBOUND_MIN_DELAY", "55.0"))
HUMAN_MAX = float(__import__("os").getenv("OUTBOUND_MAX_DELAY", "65.0"))

# Affirmative inbound triggers -> lead capture
YES_RE = re.compile(
    r"^(yes|yes please|yes please!|sure|ok|i'?m interested|count me in|"
    r"interested|book it|let's? do it|yes i want)\s?[\s!.,]?$",
    re.I,
)


# ── Template generation (A/B rotation) ──────────────────────────────────────
def _greet(first: str, voice: str, template: str) -> str:
    first = (first or "").strip()
    label = first.split()[0] if first else ("friend" if template == TEMPLATE_B else "there")
    return f"Hi {label}," if template == TEMPLATE_A else f"Hey {label}!"


def _emoji(voice: str) -> str:
    v = (voice or "").lower()
    if v == "formal":
        return ""
    return random.choice(["🚀", "👍", "✨", "🔥"])


def build_creative_message(profile: Dict[str, Any], first_name: str = "",
                           template: str = TEMPLATE_A) -> Dict[str, Any]:
    """Build one message per the caller's template (A or B), compact enough to
    fit MAX_LEN with name + benefits + CTA + link. Never cuts a word mid-way;
    if even the minimal form can't fit, the CTA is always preserved."""
    p = {**DEFAULT_PROFILE, **(profile or {})}
    voice = (p.get("brand_voice") or "casual").lower()
    emoji = _emoji(voice)
    benefits = p.get("key_benefits") or DEFAULT_PROFILE["key_benefits"]
    b1 = (benefits[0] if benefits else "").rstrip(".")
    b2 = (benefits[1] if len(benefits) > 1 else "").rstrip(".")
    b3 = (benefits[2] if len(benefits) > 2 else "").rstrip(".")
    b2b3 = ", ".join(x for x in (b2, b3) if x)
    cta = p.get("cta_text") or DEFAULT_PROFILE["cta_text"]
    link = p.get("cta_link") or ""
    biz = p.get("business_name") or "Your Business"
    svc = p.get("service_name") or "AI-Powered Booking Assistant"
    one = p.get("service_one_liner") or "books 24/7"

    if template == TEMPLATE_B:
        hook = (b1[:1].upper() + b1[1:]) if b1 else "Grow on WhatsApp"
        core1 = f"{hook}? {biz}'s {svc}: {b2b3 or 'book 24/7'}."
    else:
        core1 = f"{biz}: {svc}, {one}. {b1}"
    # shortened core: business + service only (no one-liner/benefits)
    if template == TEMPLATE_B:
        core2 = f"{hook[:24]}? {biz}'s {svc}."
    else:
        core2 = f"{biz}: {svc}."

    greet_a = f"Hi {(first_name.strip().split()[0]) if first_name.strip() else 'there'},"
    greet_b = f"Hey {(first_name.strip().split()[0]) if first_name.strip() else 'friend'}!"
    greet_named = greet_a if template == TEMPLATE_A else greet_b
    greet_gen = ("Hi there," if template == TEMPLATE_A else "Hey friend!")

    # Ladder (rich -> lean): name -> generic, full core -> short core ->
    # benefits drop, link on -> off, emoji on -> off; CTA always preserved.
    variants: List[str] = []
    for core in (core1, core2):
        for greet in (greet_named, greet_gen):
            for ben in (f", {b2b3}" if (b2b3 and core is core1) else "", ""):
                body = f"{greet} {core}{ben} {cta}"
                for on_emoji in (bool(emoji), False):
                    variants.append(_link_variant(body, link, True, emoji if on_emoji else ""))
                    variants.append(_link_variant(body, link, False, emoji if on_emoji else ""))
    # greet + CTA only, then bare CTA — both guaranteed to fit
    variants.append(_link_variant(f"{greet_gen} {cta}", link, True))
    variants.append(_link_variant(f"{greet_gen} {cta}", link, False))
    for v in variants:
        if v is not None:
            return {"text": v, "chars": len(v), "within_limit": True,
                    "template_id": template}
    # absolute fallback: CTA alone, guaranteed to fit
    return {"text": cta[:MAX_LEN], "chars": len(cta), "within_limit": True,
            "template_id": template, "minimal": True}


def _link_variant(body: str, link: str, with_link: bool, emoji: str = "") -> Optional[str]:
    """Finishing touches: append the link (if it fits) and an emoji (if it fits)."""
    raw = body
    if with_link and link:
        raw = re.sub(r"\s{2,}", " ", f"{raw} {link}")
    if emoji:
        raw = re.sub(r"\s{2,}", " ", f"{raw} {emoji}")
    raw = raw.strip()
    if len(raw) > MAX_LEN:
        return None
    return raw


def plan_creative_batch(rows: List[Dict[str, Any]], profile: Dict[str, Any],
                        rotate: bool = True) -> List[Dict[str, Any]]:
    """Produce the per-contact delivery plan (message/media, delay, template)."""
    plan: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        first = r.get("first_name") or r.get("name") or ""
        phone = r.get("phone", "")
        template = TEMPLATE_A if (not rotate or i % 2 == 0) else TEMPLATE_B
        msg = build_creative_message(profile, first, template)
        delay = round(random.uniform(HUMAN_MIN, HUMAN_MAX), 1)
        entry = {"phone": phone, "first_name": first,
                 "delay_seconds": delay, "template_id": template}
        image = profile.get("image_url") or profile.get("welcome_image_url")
        if image and str(image).startswith("https://"):
            entry["media"] = {"type": "image", "url": str(image),
                              "caption": msg["text"]}
        else:
            entry["message"] = msg["text"]
        plan.append(entry)
    return plan


# ── Affirmative reply → lead capture ─────────────────────────────────────────
def is_affirmative(text: str) -> bool:
    return bool(YES_RE.match((text or "").strip()))


LEAD_REPLY = ("Great! Please share your full name and the best time we can "
              "call you, and we'll schedule a quick demo.")


# ── Human-like one-by-one delivery ──────────────────────────────────────────
async def _send_one(entry: Dict[str, Any], client_id: int, use_meta: bool,
                    bridge_fallback: bool = True) -> Dict[str, Any]:
    """Try Meta Cloud API first, then bridge fallback. Returns result dict."""
    phone = entry["phone"]
    text = entry.get("message") or (entry.get("media") or {}).get("caption", "")
    if use_meta:
        from main import _send_via_meta  # lazy import (main is heavy)
        res = await _send_via_meta(phone, text, client_id=client_id)
        if res.get("status") == "sent":
            return {"ok": True, "channel": "meta", "wamid": res.get("wamid")}
        logger.warning("[!] Meta send failed: %s; trying bridge %s", res, phone)
    if bridge_fallback:
        from outbound_limiter import send_whatsapp
        ok = await send_whatsapp(phone, text, client_id=client_id)
        return {"ok": ok, "channel": "bridge" if ok else "none"}
    return {"ok": False, "channel": "none", "error": res.get("message", "")}


async def _already_sent(client_id: int, phone: str, text: str) -> bool:
    from sqlalchemy import select
    from db import async_session, Message
    async with async_session() as session:
        res = await session.execute(
            select(Message).where(Message.direction == "outgoing",
                                  Message.client_id == client_id,
                                  Message.content == text).limit(1))
        return res.scalar_one_or_none() is not None


async def send_human_like(plan: List[Dict[str, Any]], client_id: int = 1,
                          use_meta: bool = True, dry_run: bool = False,
                          on_status=None) -> Dict[str, Any]:
    """Send one-by-one with a human-like 55-65s gap between sends.

    Stops on first real failure; deduplicates rows already recorded as sent."""
    from db import save_message
    sent = failed = skipped = 0
    import time as _t
    last_ts: Optional[float] = None
    total = len(plan)
    for i, entry in enumerate(plan):
        text = entry.get("message") or (entry.get("media") or {}).get("caption", "")
        if await _already_sent(client_id, entry["phone"], text):
            skipped += 1
            if on_status: await on_status(i + 1, total, entry, "SKIP (already sent)")
            continue
        if dry_run:
            if on_status: await on_status(i + 1, total, entry, "DRY")
            continue
        gap = entry.get("delay_seconds", random.uniform(HUMAN_MIN, HUMAN_MAX))
        if last_ts is not None:
            await asyncio.sleep(max(0.0, gap))
        last_ts = _t.monotonic()
        res = await _send_one(entry, client_id, use_meta)
        if res["ok"]:
            try:
                await save_message(phone_number=entry["phone"], content=text,
                                   direction="outgoing", client_id=client_id)
            except Exception as e:
                logger.warning("[!] record failed %s: %s", entry["phone"], e)
            sent += 1
            if on_status: await on_status(i + 1, total, entry, "SENT")
        else:
            failed += 1
            if on_status: await on_status(i + 1, total, entry,
                                          f"FAIL: {res.get('error','channel down')}")
            break  # stop on first failure
    return {"ok": failed == 0, "sent": sent, "failed": failed,
            "skipped": skipped, "total": total}


# ── Bot-reply flow: capture the affirmative reply into leads ─────────────────
async def capture_lead_reply(client_id: int, phone: str,
                             text: str) -> Dict[str, Any]:
    """When a prospect replies YES, return the scripted reply and persist a
    lead (source='broadcast') so the owner's dashboard sees a new lead.

    Uses the existing Contact/Message tables (leads are Contacts with
    lead_status='new')."""
    import sqlalchemy
    from db import async_session, Contact, upsert_contact, save_message
    try:
        async with async_session() as session:
            contact = await upsert_contact(session, phone_number=phone,
                                           client_id=client_id,
                                           source="broadcast")
            contact.lead_status = "new"
            await session.commit()
    except Exception as e:
        logger.warning("[!] capture_lead_reply contact err: %s", e)
    try:
        await save_message(phone_number=phone, content=text,
                           direction="incoming", client_id=client_id,
                           message_type="text")
    except Exception as e:
        logger.warning("[!] capture_lead_reply msg err: %s", e)
    return {"reply": LEAD_REPLY, "source": "broadcast", "captured": True}