"""
Advanced, per-client System Prompt builder.

Every client_id gets a distinct persona, knowledge base, guardrails, tone and
goal built f-string style from that shop's real profile (name, industry,
services, pricing, selling points, tone, contact info).

Load path: AgentEngine/business_profiles.py (JSON) -> database (clients or
business profiles table). Falls back to a safe generic persona so the bot
never crashes when a profile is missing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("prompt_builder")

# Default human-friendly names for the guardrail/tone placeholders.
DEFAULT_TONE = "friendly and professional"
OFFLINE_FALLBACK = (
    "I don't have that exact information on hand, but I will have the owner "
    "contact you shortly."
)


def _industry_label(business_type: str) -> str:
    """Turn the internal business_type into a natural industry noun."""
    mapping = {
        "restaurant": "restaurant",
        "hotel": "hotel",
        "doctor": "clinic / doctor's practice",
        "ca": "chartered accountancy firm",
        "lawyer": "law firm / legal practice",
        "salon": "salon",
        "retail": "retail shop",
        "education": "educational institute",
    }
    return mapping.get((business_type or "").lower(), (business_type or "local shop"))

def load_business_profile(client_id: int) -> Optional[Dict[str, Any]]:
    """Load a business's rich profile dict for a client_id.

    Tries the file-backed business_manager first (the main per-client store),
    then the DB 'clients' table. Returns None when no profile exists.
    """
    try:
        from business_profiles import business_manager
        for profile in business_manager.profiles.values():
            if profile.client_id == int(client_id):
                btype = profile.business_type.value \
                    if hasattr(profile.business_type, "value") else str(profile.business_type)
                catalog = []
                try:
                    catalog = business_manager.get_catalog(profile.id) or []
                except Exception:
                    catalog = []
                services = [c.get("name") for c in catalog
                            if c.get("name")] or [getattr(profile, "description", "")]
                pricing = [
                    f"{c.get('name')} - {getattr(profile, 'currency', 'INR')} {c.get('price', 0)}"
                    for c in catalog if c.get("name")
                ]
                address = getattr(profile, "address", "") or ""
                city = _extract_city(address)
                return {
                    "business_name": getattr(profile, "name", "") or "this business",
                    "industry": _industry_label(btype),
                    "city": city,
                    "services": [s for s in services if s],
                    "pricing": pricing,
                    "selling_points": [getattr(profile, "description", "")] if getattr(profile, "description", "") else [],
                    "tone": DEFAULT_TONE,
                    "contact_phone": getattr(profile, "contact_phone", "") or "",
                    "contact_email": getattr(profile, "contact_email", "") or "",
                    "address": address,
                    "working_hours": getattr(profile, "working_hours", None) or "",
                    "payment_methods": getattr(profile, "payment_methods", []) or [],
                    "welcome_message": getattr(profile, "welcome_message", "") or "",
                    "currency": getattr(profile, "currency", "INR") or "INR",
                }
    except Exception as e:
        logger.warning("load_business_profile(file) failed for client %s: %s", client_id, e)

    try:
        from sqlalchemy import select
        from db import async_session, Client
        import asyncio

        async def _fetch():
            async with async_session() as session:
                res = await session.execute(
                    select(Client).where(Client.id == int(client_id)))
                return res.scalar_one_or_none()

        # Sync-safe DB fetch: if we're already inside a running event loop,
        # skip (the file-backed store is the primary path); otherwise run the
        # coroutine on a fresh loop (safe in CLI/script contexts).
        try:
            asyncio.get_running_loop()
            client = None  # already async context -> rely on file store/caller
        except RuntimeError:
            client = asyncio.run(_fetch())
        if client:
            return {
                "business_name": client.business_name or "this business",
                "industry": _industry_label(client.vertical or "general"),
                "city": "",
                "services": [],
                "pricing": [],
                "selling_points": [],
                "tone": DEFAULT_TONE,
                "contact_phone": client.whatsapp_number or "",
                "contact_email": "",
                "address": "",
                "working_hours": "",
                "payment_methods": [],
                "welcome_message": "",
                "currency": "INR",
            }
    except Exception as e:
        logger.warning("load_business_profile(db) failed for client %s: %s", client_id, e)

    return None


def _extract_city(address: str) -> str:
    """Best-effort city guess from an address (last non-numeric token)."""
    try:
        parts = [w for w in address.replace(",", " ").split()
                 if w and not any(ch.isdigit() for ch in w)]
        return parts[-1] if parts else ""
    except Exception:
        return ""


def build_advanced_system_prompt(business_profile: Dict[str, Any]) -> str:
    """Build the full advanced System Message from a business profile dict."""
    b = business_profile or {}

    business_name = b.get("business_name") or "this business"
    industry = b.get("industry") or "local shop"
    city = b.get("city") or "your area"
    services = b.get("services") or []
    pricing = b.get("pricing") or []
    selling_points = b.get("selling_points") or []
    tone = b.get("tone") or DEFAULT_TONE
    contact_phone = b.get("contact_phone") or ""
    contact_email = b.get("contact_email") or ""
    address = b.get("address") or ""
    working_hours = b.get("working_hours") or ""
    payment_methods = b.get("payment_methods") or []

    services_block = "\n".join(f"- {s}" for s in services) or "- (services list not provided)"
    pricing_block = "\n".join(f"- {p}" for p in pricing) or "- (pricing not provided)"
    selling_block = "\n".join(f"- {sp}" for sp in selling_points) or "- (selling points not provided)"
    hours_block = working_hours if isinstance(working_hours, str) and working_hours \
        else (", ".join(f"{k}: {v}" for k, v in working_hours.items()) if isinstance(working_hours, dict) else "not provided")
    payments_block = ", ".join(payment_methods) if payment_methods else "not listed"

    return f"""You are the official AI receptionist for {business_name}, a {industry} located in {city}.

## PERSONA & IDENTITY
- Represent {business_name} warmly and accurately. You are the friendly, reliable first point of contact.
- Never pretend to be a different business, and never act like a generic assistant.

## KNOWLEDGE BASE (use ONLY these facts)
Services offered by {business_name}:
{services_block}

Pricing (exact, from the business catalogue — use these numbers only):
{pricing_block}

Key selling points to emphasise:
{selling_block}

Business details:
- Address: {address if address else "not provided"}
- Working hours: {hours_block}
- Accepted payments: {payments_block}
- Contact: {contact_phone}{(' | ' + contact_email if contact_email else '')}

## STRICT GUARDRAILS (ANTI-HALLUCINATION)
- Do NOT make up prices, discounts, services, availability, or offers.
- Only quote a price, service, or fact if it appears in the knowledge base above.
- If a customer asks a question NOT covered in the knowledge base, you MUST reply exactly:
  "{OFFLINE_FALLBACK}"
- Never invent timings, staff, or policies.

## TONE & FORMATTING
- Use a {tone} tone.
- Keep responses short and readable for WhatsApp (use emojis sparingly, use bullet points for lists).
- Mirror the customer's language (Hindi, English, or Hinglish) naturally.

## GOAL
- Your primary goal is to answer FAQs and collect the customer's requirements to book an appointment or generate a lead.
- Politely gather: name, preferred date/time (if relevant), and the specific service/product they need.
- Pass complete booking/order intents through so they can be processed.
"""


def build_system_prompt_for_client(client_id: int) -> str:
    """One-call convenience: load the client's profile and build its prompt."""
    return build_advanced_system_prompt(load_business_profile(client_id) or {})

