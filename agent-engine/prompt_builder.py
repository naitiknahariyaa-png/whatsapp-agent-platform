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
                out = {
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
                # pass through business-provided media URLs (prompt allowlist)
                for _k in ("welcome_image_url", "gallery_images",
                           "menu_image_url", "product_images", "logo_url"):
                    _v = getattr(profile, _k, None)
                    if _v:
                        out[_k] = _v
                return out
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
            # Merge the onboarding profile.json blob (menu / brand_voice /
            # languages / business_hours) stored on Client.business_profile.
            extra: Dict[str, Any] = {}
            try:
                if isinstance(client.business_profile, dict):
                    extra = client.business_profile
            except Exception:
                extra = {}
            menu = extra.get("menu") or []
            merged_pricing = [
                f"{m.get('name')} - {extra.get('currency', 'INR')} {m.get('price', 0)}"
                for m in menu if isinstance(m, dict) and m.get("name")
            ]
            out = {
                "business_name": client.business_name or "this business",
                "industry": _industry_label(client.vertical or "general"),
                "city": "",
                "services": [m.get("name") for m in menu
                             if isinstance(m, dict) and m.get("name")],
                "pricing": merged_pricing,
                "selling_points": [],
                "tone": extra.get("brand_voice") or DEFAULT_TONE,
                "contact_phone": client.whatsapp_number or "",
                "contact_email": "",
                "address": "",
                "working_hours": extra.get("business_hours") or "",
                "payment_methods": [],
                "welcome_message": "",
                "currency": extra.get("currency", "INR") or "INR",
            }
            # business-provided media URLs for the prompt allowlist
            for _k in ("welcome_image_url", "gallery_images",
                       "menu_image_url", "product_images", "logo_url"):
                if extra.get(_k):
                    out[_k] = extra[_k]
            return out
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


def _vertical_guidelines(business_type: str, profile: Dict[str, Any]) -> str:
    """Per-vertical tone/vocabulary/media guidelines for the outbound message
    template (Sales-Assistant-AI behaviour spec)."""
    bt = (business_type or "").lower()
    if bt in ("doctor", "healthcare", "clinic"):
        return """## VERTICAL GUIDELINES — DOCTOR / HEALTHCARE
- Calm, professional tone. Mention: consultation, appointment, clinic hours, prescription.
- If the customer asks to SEE something (clinic, facility), use ONLY the image URL in
  welcome_image_url if provided. Never send any other image."""
    if bt in ("salon", "beauty"):
        return """## VERTICAL GUIDELINES — SALON / BEAUTY
- Friendly, upbeat tone; emojis are allowed.
- Vocabulary: haircut, styling package, special offer, "book your makeover".
- If asked for pictures, send the before/after gallery image from gallery_images
  (if provided)."""
    if bt in ("restaurant", "food", "hotel"):
        return """## VERTICAL GUIDELINES — RESTAURANT / FOOD
- Warm, inviting tone. Include actual dish names, "today's special", reservation times.
- Offer a menu-preview image from menu_image_url (if provided) when the customer asks."""
    if bt in ("retail", "e-commerce", "ecommerce", "shop"):
        return """## VERTICAL GUIDELINES — RETAIL / E-COMMERCE
- Concise messages. Always highlight: product name, price, and any discount code
  from the catalog/business details.
- Attach the matching product photo URL from product_images (if provided)."""
    if bt in ("lawyer", "ca", "legal", "accountant", "chartered accountant"):
        return """## VERTICAL GUIDELINES — LEGAL / CA / ACCOUNTANT
- Formal, respectful tone. NO emojis.
- Vocabulary: consultation fee, document preparation, court date, filing deadline.
- Only send a professional logo image (logo_url, if provided) — nothing else."""
    voice = profile.get("brand_voice") or "friendly and professional"
    return f"""## VERTICAL GUIDELINES — GENERAL
- Use the business's brand voice: {voice}.
- Follow the knowledge base and guardrails above strictly; fall back to
  "{OFFLINE_FALLBACK}" for anything not covered."""


def _media_fields_block(profile: Dict[str, Any]) -> str:
    """List the business-provided media URLs the assistant may send (allowlist)."""
    keys = ("welcome_image_url", "gallery_images", "menu_image_url",
            "product_images", "logo_url")
    lines = []
    for k in keys:
        v = profile.get(k)
        if isinstance(v, str) and v.startswith("https://"):
            lines.append(f"- {k}: {v}")
        elif isinstance(v, list):
            lines.append(f"- {k}: " + ", ".join(
                u for u in v if isinstance(u, str) and u.startswith("https://")))
    if not lines:
        return ("- No media URLs provided. Do NOT send any photos or files; "
                "describe in text instead.")
    return ("\n".join(lines) +
            "\n- ONLY these URLs may be sent as media. Never invent or "
            "substitute a URL.")


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

    guidelines = _vertical_guidelines(industry, b)
    media_block = _media_fields_block(b)

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

## VERTICAL GUIDELINES & MEDIA
{guidelines}

Media you may send (allowlist):
{media_block}

## OUTBOUND MESSAGE TEMPLATE (apply to EVERY message)
1. Greet/acknowledge in the customer's language, in the vertical's tone.
2. Address their specific question/request using ONLY the knowledge base above.
3. If media helps (and an allowlisted URL fits), include it — otherwise describe in text.
4. Recommend ONE concrete next step (appointment, package, product, demo).
5. Close warmly in the vertical's tone. Keep it WhatsApp-length (short paragraphs).

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


def build_system_prompt(profile: Optional[Dict[str, Any]]) -> str:
    """Build a per-shop system prompt from a raw ``profile.json``-shaped dict.

    Accepts the onboarding-wizard profile format (see ``business-setup`` /
    ``upload-profile``)::

        {
          "menu": [{"name": "Service A", "price": 199, "category": "hair"}],
          "brand_voice": "casual",
          "languages": ["hi", "en"],
          "business_hours": "Mon-Sat 09:00-21:00"
        }

    and produces a prompt with brand voice, menu items, and the same
    anti-hallucination guardrails as :func:`build_advanced_system_prompt`
    (they share the OFFLINE_FALLBACK wording so behaviour stays consistent).
    Safe on ``None``/empty input — falls back to a generic-but-guarded prompt.
    """
    p = profile or {}
    business_name = p.get("business_name") or p.get("name") or "this business"
    brand_voice = str(p.get("brand_voice") or "friendly and professional")
    languages = p.get("languages") or ["en", "hi"]
    hours = p.get("business_hours") or p.get("working_hours") or "not provided"
    contact = p.get("contact_phone") or p.get("phone") or ""
    currency = p.get("currency", "INR")

    menu = p.get("menu") or p.get("catalog") or []
    if isinstance(menu, dict):
        menu = [{"name": k, "price": v} for k, v in menu.items()]
    menu_block = "\n".join(
        f"- {m.get('name', '?')}: {currency} {m.get('price', '?')}"
        + (f" (category: {m['category']})" if m.get("category") else "")
        for m in menu if isinstance(m, dict) and m.get("name")
    ) or "- (menu not provided — do NOT invent items or prices)"

    langs = ", ".join(languages) if isinstance(languages, list) else str(languages)

    guidelines = _vertical_guidelines(p.get("business_type") or p.get("vertical"), p)
    media_block = _media_fields_block(p)

    return f"""You are the official AI receptionist for {business_name} on WhatsApp.

## BRAND VOICE
- Communicate in a {brand_voice} tone at all times.
- Reply in the customer's language; preferred languages: {langs}.

## MENU / CATALOGUE (use ONLY these items and prices)
{menu_block}

Business hours: {hours}
{('- Contact: ' + contact) if contact else ''}

{guidelines}

Media you may send (allowlist):
{media_block}

## OUTBOUND MESSAGE TEMPLATE (apply to EVERY message)
1. Greet/acknowledge in the customer's language, in the vertical's tone.
2. Answer using ONLY the menu and details above.
3. Include media only when an allowlisted URL fits; otherwise describe in text.
4. Recommend ONE concrete next step, then close warmly.

## STRICT GUARDRAILS (ANTI-HALLUCINATION)
- Do NOT make up prices, discounts, items, availability, or offers.
- Only quote an item or price if it appears in the menu above.
- If asked about something NOT in the menu or business details, reply exactly:
  "{OFFLINE_FALLBACK}"
- Never invent timings, staff, or policies.

## GOAL
- Answer FAQs using only the facts above and collect the customer's
  requirements (name, item/service, preferred time) to generate a lead.
"""


def build_system_prompt_for_client(client_id: int) -> str:
    """One-call convenience: load the client's profile and build its prompt."""
    return build_advanced_system_prompt(load_business_profile(client_id) or {})

