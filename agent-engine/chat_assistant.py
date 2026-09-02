"""
Multi-Business Chat Assistant — web chat widget backend logic.

Flow:
1. Receive customer message + business context
2. Call LLM with structured system prompt
3. Parse JSON response (intent, extracted fields, reply)
4. If booking is ready: save to DB + notify owner via WhatsApp
5. Return reply_to_customer to the widget
"""
import os
import json
import re
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from config import settings
from llm_setup import get_llm
from db import async_session, create_booking, upsert_contact, Booking
from sqlalchemy import select

logger = logging.getLogger("chat_assistant")


# ---------------------------------------------------------------------------
# Business config builder
# ---------------------------------------------------------------------------

def build_business_config(business_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Build the business_config block injected into the system prompt."""
    biz_type = profile.get("business_type", "general")
    name = profile.get("name", "Our Business")
    desc = profile.get("description", "")
    hours = profile.get("working_hours", {})
    hours_str = ", ".join([f"{k}: {v}" for k, v in hours.items()]) if hours else "Contact for hours"
    contact_phone = profile.get("contact_phone", "")
    contact_email = profile.get("contact_email", "")

    # Determine booking fields based on business type
    booking_fields = ["date", "time", "customer_name", "customer_contact"]
    if biz_type in ("restaurant", "hotel"):
        booking_fields.append("party_size")
    if biz_type in ("salon", "doctor", "ca", "lawyer", "education"):
        booking_fields.append("service_type")

    # Services/categories from catalog
    categories = []
    catalog_items = []
    try:
        from business_profiles import business_manager
        found_catalog = []
        for p in business_manager.profiles.values():
            if p.id == business_id and getattr(p, "is_active", True):
                found_catalog = business_manager.get_catalog(p.id) or []
                break
        if not found_catalog:
            # fall back to the client's catalog when id is 'default'
            for p in business_manager.profiles.values():
                if getattr(p, "client_id", None) == client_id:
                    found_catalog = business_manager.get_catalog(p.id) or []
                    break
        categories = list(set(item.get("category", "") for item in found_catalog if item.get("category")))
        catalog_items = [
            {"name": it.get("name"), "price": it.get("price"),
             "category": it.get("category"), "available": it.get("is_available", True)}
            for it in found_catalog[:30]
        ]
    except Exception:
        pass

    # Services list for non-catalog businesses
    services = []
    if biz_type == "doctor":
        services = ["General consultation", "Follow-up visit", "Vaccination"]
    elif biz_type == "salon":
        services = ["Haircut", "Facial", "Massage", "Manicure", "Pedicure"]
    elif biz_type == "ca":
        services = ["ITR Filing", "GST Return", "Audit", "Company Registration"]
    elif biz_type == "lawyer":
        services = ["Property", "Divorce", "Criminal", "Corporate", "Civil"]
    elif biz_type == "education":
        services = ["Class 1-5", "Class 6-10", "Class 11-12", "JEE/NEET", "Spoken English"]

    # Selling points (explicit or derived)
    selling_points = profile.get("selling_points") or []
    if not selling_points and profile.get("description"):
        selling_points = [profile["description"]]

    return {
        "business_name": name,
        "business_type": biz_type,
        "description": desc,
        "hours": hours_str,
        "contact_phone": contact_phone,
        "contact_email": contact_email,
        "address": profile.get("address", ""),
        "payment_methods": profile.get("payment_methods", []),
        "delivery_enabled": profile.get("delivery_enabled", False),
        "welcome_message": profile.get("welcome_message", ""),
        "categories": categories,
        "services": services,
        "catalog": catalog_items,
        "selling_points": selling_points,
        "booking_fields": booking_fields,
    }


def render_business_config(config: Dict[str, Any]) -> str:
    """Render business_config dict as a JSON string for the system prompt."""
    return json.dumps(config, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are a virtual assistant for {business_name}, a {business_type}.

Your job on every incoming message:
1. Classify the customer's INTENT.
2. Extract any structured details already given.
3. Decide if you have enough info to complete a booking, or need to ask a follow-up question.
4. Write a natural, warm reply to send back to the customer.
5. If the customer seems hesitant, uninterested, or asking generic questions (e.g. "hi", "what's on the menu") without booking, gently guide them toward booking/ordering using their stated interest — never pushy, never make up discounts or facts you weren't given.

INTENTS (pick exactly one):
- "booking_request"   → wants to book a table / appointment / slot
- "service_inquiry"   → asking about menu, services, prices, hours
- "modify_booking"    → wants to change/cancel an existing booking
- "complaint"         → unhappy about a past experience
- "general_chat"      → greeting, small talk, unclear intent

REQUIRED FIELDS for a "booking_request" to be marked ready_to_book = true:
- date
- time
- party_size (for restaurant/hotel) OR service_type (for salon/doctor/ca/lawyer/education)
- customer_name
- customer_contact (phone or email)

If any required field is missing, set ready_to_book = false and make your reply ASK for exactly the missing field(s) — one short question, not a list of five questions at once.

Never invent availability, prices, or promises you were not given in the business config. If you don't know something, say you'll have the team confirm it.

Business config (fill in per client):
{business_config}

Respond ONLY with a single JSON object in this exact shape, nothing else:

{{
  "intent": "booking_request | service_inquiry | modify_booking | complaint | general_chat",
  "ready_to_book": true | false,
  "extracted": {{
    "date": "string or null",
    "time": "string or null",
    "party_size": "number or null",
    "service_type": "string or null",
    "customer_name": "string or null",
    "customer_contact": "string or null",
    "notes": "string or null"
  }},
  "reply_to_customer": "the exact message text to show the customer"
}}"""


# ---------------------------------------------------------------------------
# Speak-as-the-business persona
# ---------------------------------------------------------------------------

PERSONA_INSTRUCTION = """You are speaking AS the business described below. When a customer
asks about the business (name, what you sell, prices, hours, how to book), answer confidently
using the facts given — never say you don't have information about your own business. Only reply
'let me check with the owner' for facts genuinely not provided.
"""


# ---------------------------------------------------------------------------
# LLM call + JSON parsing
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON from LLM response, tolerating markdown fences."""
    # Strip markdown code fences if present
    text = re.sub(r'```(?:json)?', '', text).strip()
    # Find the first JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


async def call_chat_llm(system_prompt: str, user_message: str, history: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Call the LLM and return parsed JSON response."""
    llm = get_llm()

    # Build messages
    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [SystemMessage(content=system_prompt)]

    if history:
        for h in history[-6:]:
            role = "User" if h.get("direction") == "incoming" else "Assistant"
            messages.append(HumanMessage(content=f"{role}: {h.get('content', '')}"))

    messages.append(HumanMessage(content=user_message))

    try:
        if hasattr(llm, 'invoke'):
            response = await asyncio.to_thread(llm.invoke, messages)
            text = response.content if hasattr(response, 'content') else str(response)
        else:
            # MockLLM fallback — generate a sensible default
            return {
                "intent": "general_chat",
                "ready_to_book": False,
                "extracted": {
                    "date": None, "time": None, "party_size": None,
                    "service_type": None, "customer_name": None,
                    "customer_contact": None, "notes": None
                },
                "reply_to_customer": "Hi! How can I help you today? You can ask about our services or book an appointment."
            }

        parsed = _extract_json(text)
        if not parsed:
            logger.warning("[!] Failed to parse LLM JSON response: %s", text[:200])
            return {
                "intent": "general_chat",
                "ready_to_book": False,
                "extracted": {
                    "date": None, "time": None, "party_size": None,
                    "service_type": None, "customer_name": None,
                    "customer_contact": None, "notes": None
                },
                "reply_to_customer": "I'm here to help! Could you tell me a bit more about what you need?"
            }

        # Validate and normalize
        parsed.setdefault("intent", "general_chat")
        parsed.setdefault("ready_to_book", False)
        parsed.setdefault("reply_to_customer", "Thanks for your message!")
        extracted = parsed.get("extracted", {})
        for field in ["date", "time", "party_size", "service_type", "customer_name", "customer_contact", "notes"]:
            extracted.setdefault(field, None)
        parsed["extracted"] = extracted
        return parsed

    except Exception as e:
        logger.error("[!] LLM call failed: %s", e)
        return {
            "intent": "general_chat",
            "ready_to_book": False,
            "extracted": {
                "date": None, "time": None, "party_size": None,
                "service_type": None, "customer_name": None,
                "customer_contact": None, "notes": None
            },
            "reply_to_customer": "I'm having a small issue right now. Please try again in a moment."
        }


# ---------------------------------------------------------------------------
# Owner notification
# ---------------------------------------------------------------------------

async def notify_owner_via_whatsapp(business: Dict[str, Any], booking_data: Dict[str, Any]) -> bool:
    """Send a WhatsApp message to the business owner about a new booking."""
    owner_phone = business.get("contact_phone", "")
    if not owner_phone:
        return False

    biz_name = business.get("name", "Business")
    intent = booking_data.get("intent", "booking_request")
    extracted = booking_data.get("extracted", {})

    lines = [f"New {intent.replace('_', ' ')} via web chat!"]
    lines.append(f"Business: {biz_name}")
    if extracted.get("customer_name"):
        lines.append(f"Customer: {extracted['customer_name']}")
    if extracted.get("customer_contact"):
        lines.append(f"Contact: {extracted['customer_contact']}")
    if extracted.get("date"):
        lines.append(f"Date: {extracted['date']}")
    if extracted.get("time"):
        lines.append(f"Time: {extracted['time']}")
    if extracted.get("party_size"):
        lines.append(f"Party size: {extracted['party_size']}")
    if extracted.get("service_type"):
        lines.append(f"Service: {extracted['service_type']}")
    if extracted.get("notes"):
        lines.append(f"Notes: {extracted['notes']}")

    message = "\n".join(lines)

    # Send through the anti-ban limiter (cap + cooldown + randomized 5-20s delay).
    try:
        from outbound_limiter import send_whatsapp
        client_id = business.get("client_id", 1)
        return await send_whatsapp(owner_phone, message, client_id=client_id)
    except Exception as e:
        logger.warning("[!] Owner WhatsApp notification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def process_chat_message(
    business_id: str,
    customer_message: str,
    customer_identifier: str = "",
    history: Optional[List[Dict]] = None,
    client_id: int = 1,
) -> Dict[str, Any]:
    """
    Process a web chat message end-to-end.

    Returns:
        {
            "reply_to_customer": str,
            "intent": str,
            "ready_to_book": bool,
            "extracted": dict,
            "booking_saved": bool,
            "owner_notified": bool
        }
    """
    # 1. Load business profile — resolve the real owner business when the
    #    widget sends 'default'/'web' (it does not know its own business id).
    profile = {}
    try:
        from business_profiles import business_manager
        active = [p for p in business_manager.profiles.values() if getattr(p, "is_active", True)]
        # if the client_id maps to a real profile, prefer it (multi-tenant)
        by_client = next((p for p in active
                          if getattr(p, "client_id", None) == client_id), None)
        by_id = next((p for p in active if p.id == business_id), None)
        resolved = by_id or by_client
        if resolved is None and len(active) == 1:
            resolved = active[0]  # single-business fallback
        if resolved is not None:
            profile = resolved.to_dict()
            if business_id not in ("default", "web", ""):
                pass  # honoured exact id
            # honour the requested business id even if it differs from client
            if by_id is not None or business_id in ("default", "web", ""):
                profile["id"] = profile.get("id") or business_id
    except Exception as e:
        logger.warning("[!] Could not load business profile: %s", e)

    if not profile:
        profile = {"id": business_id, "name": "Our Business", "business_type": "general"}
        try:
            from business_profiles import business_manager
            if business_manager.profiles:
                first = next(iter(business_manager.profiles.values()))
                profile = first.to_dict()
        except Exception:
            pass

    # 2. Build prompt
    biz_config = build_business_config(business_id, profile)
    # Inject the "speak-as-the-business" persona so the widget answers with the
    # business's real name, services, prices and facts — not a generic reply.
    persona = ""
    try:
        from cli_commands import build_business_system_prompt
        persona = build_business_system_prompt(profile, catalog=biz_config.get("catalog"))
    except Exception as e:
        logger.warning("[!] persona build failed: %s", e)
    persona_block = f"\n\n{PERSONA_INSTRUCTION}\n{persona}\n" if persona else ""

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        business_name=biz_config["business_name"],
        business_type=biz_config["business_type"],
        business_config=render_business_config(biz_config),
    ) + persona_block

    # 3. Call LLM
    llm_result = await call_chat_llm(system_prompt, customer_message, history)

    # 4. Save booking if ready
    booking_saved = False
    owner_notified = False

    if llm_result.get("intent") == "booking_request" and llm_result.get("ready_to_book"):
        try:
            async with async_session() as session:
                # Upsert contact
                contact = await upsert_contact(
                    session,
                    phone_number=customer_identifier or llm_result.get("extracted", {}).get("customer_contact", ""),
                    client_id=client_id,
                    name=llm_result.get("extracted", {}).get("customer_name", ""),
                )
                contact_id = contact.id

                # Save booking
                booking = await create_booking(
                    session,
                    client_id=client_id,
                    business_id=business_id,
                    business_type=biz_config["business_type"],
                    extracted=llm_result.get("extracted", {}),
                    source="web_chat",
                )
                booking.contact_id = contact_id
                await session.commit()
                booking_saved = True
                logger.info("[v] Booking saved: id=%s, business=%s", booking.id, business_id)

                # Notify owner
                owner_notified = await notify_owner_via_whatsapp(profile, llm_result)
                if owner_notified:
                    logger.info("[v] Owner notified via WhatsApp for booking %s", booking.id)
        except Exception as e:
            logger.error("[!] Failed to save booking: %s", e)

    return {
        "reply_to_customer": llm_result.get("reply_to_customer", ""),
        "intent": llm_result.get("intent", "general_chat"),
        "ready_to_book": llm_result.get("ready_to_book", False),
        "extracted": llm_result.get("extracted", {}),
        "booking_saved": booking_saved,
        "owner_notified": owner_notified,
    }
