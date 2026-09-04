"""
Agent Orchestrator - Routes incoming WhatsApp messages through intent detection,
state machine, vertical bots and LLM response generation.

This module is intentionally resilient: any optional/vertical dependency is
imported lazily inside a guarded block so a single broken submodule can never
prevent the orchestrator (and therefore the whole app) from importing.

Multi-tenancy: every DB touch is scoped by `client_id`, which is threaded
through from the webhook. Observability: structured logs, metrics and usage
metering are emitted via logging_setup + metrics + usage_metering.
"""
from __future__ import annotations

import json
import re
import asyncio
from typing import Optional, List, Dict, Any

from logging_setup import get_logger, log_metric, bind_context
from language import detect_language, localize
from model_router import get_classification_llm, get_generation_llm, get_extraction_llm

logger = get_logger("orchestrator")

try:
    from db import get_session, save_message, get_conversation_history, upsert_contact
    DB_OK = True
except Exception as e:  # pragma: no cover
    DB_OK = False
    logger.warning("db import failed: %s", e)

try:
    from config import settings
except Exception:  # pragma: no cover
    settings = None

try:
    from state_machine import get_state_machine
except Exception:  # pragma: no cover
    get_state_machine = None

try:
    from handoff import request_handoff
except Exception:  # pragma: no cover
    request_handoff = None


def _safe_call(fn, *args, **kwargs):
    """Call an optional callable; return None on any failure."""
    try:
        return fn(*args, **kwargs) if callable(fn) else None
    except Exception as e:  # pragma: no cover
        logger.debug("optional call failed: %s", e)
        return None


class IntentDetector:
    """LLM-based intent + entity extraction with keyword fallback."""

    def __init__(self):
        self.classification_llm = get_classification_llm()
        self.extraction_llm = get_extraction_llm()
        self._provider_status = {}

    async def detect(self, message: str, history: List[Dict], lang: str = "en") -> dict:
        context = ""
        if history:
            context = "\n".join([
                f"{'User' if h['direction'] == 'incoming' else 'Bot'}: {h['content']}"
                for h in history[-5:]
            ])

        lang_hint = f"The user is writing in {lang}. If you reply, do so in {lang}."
        prompt = f"""You are an intent classifier for a WhatsApp AI assistant for Indian businesses.
Analyse the user message and classify it into ONE of these intents:

- greeting: Hello, hi, namaste, good morning, etc.
- farewell: Bye, goodbye, alvida, thank you, etc.
- appointment_booking: Book, schedule, appointment, meeting, slot, visit, table booking
- pricing_query: Price, cost, rate, fees, charges, kitna, etc.
- support: Help, problem, issue, error, not working
- lead_enquiry: Interested, buy, purchase, subscribe, chahiye
- document_request: Document, upload, file, pdf, photo, image
- symptom_check: Fever, cough, cold, headache, pain, bukhar, khansi, dard
- prescription_request: Prescription, dawai, medicine
- lab_report: Lab, report, test, blood
- case_inquiry: Case, court, legal, mukadma, property dispute, divorce, criminal
- itr_inquiry: ITR, tax, GST, income tax, return filing, deadline
- menu_inquiry: Menu, food, khana, order, delivery
- order_placement: Want to order food/products, add to cart, buy now
- payment_request: Pay, payment, razorpay, upi, paisa, bhugtan
- human_handoff: Human, agent, real person, talk to human
- general_query: Anything else

Also extract these entities if present:
- date, time, person_name, location, product_name, quantity, phone_number

Return ONLY valid JSON (no markdown, no extra text):
{{"intent": "intent_name", "confidence": 0.95, "entities": {{"date": "", "time": "", "person_name": "", "location": "", "product_name": "", "quantity": "", "phone_number": ""}}, "action": "create_order|create_appointment|save_lead|send_info|none"}}

Previous conversation:
{context}

User message: {message}
{lang_hint}

JSON response:"""

        try:
            if self.classification_llm is not None and hasattr(self.classification_llm, 'invoke'):
                response = await asyncio.to_thread(self.classification_llm.invoke, prompt)
                result_text = response.content if hasattr(response, 'content') else str(response)
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                    return {
                        "intent": result.get("intent", "general_query"),
                        "confidence": float(result.get("confidence", 0.7)),
                        "entities": result.get("entities", {}),
                        "action": result.get("action", "none"),
                    }
        except Exception as e:
            logger.warning("LLM intent detection failed: %s", e)

        return self._keyword_fallback(message)

    def _keyword_fallback(self, message: str) -> dict:
        msg = message.lower()
        rules = [
            (["hello", "hi", "hey", "namaste", "namaskar"], "greeting", 0.9),
            (["bye", "goodbye", "alvida", "dhanyavad", "thank"], "farewell", 0.9),
            (["appointment", "book", "schedule", "meeting", "slot", "visit", "table"], "appointment_booking", 0.85),
            (["price", "cost", "rate", "kitna", "charges", "fees"], "pricing_query", 0.85),
            (["help", "support", "problem", "issue", "error"], "support", 0.8),
            (["fever", "cough", "cold", "headache", "pain", "bukhar", "khansi"], "symptom_check", 0.85),
            (["prescription", "dawai", "medicine"], "prescription_request", 0.85),
            (["lab", "report", "test", "blood"], "lab_report", 0.85),
            (["case", "court", "legal", "mukadma", "property dispute", "divorce"], "case_inquiry", 0.85),
            (["itr", "tax", "gst", "income tax", "deadline"], "itr_inquiry", 0.85),
            (["menu", "food", "khana", "order"], "menu_inquiry", 0.85),
            (["pay", "payment", "razorpay", "upi", "paisa", "bhugtan"], "payment_request", 0.85),
            (["human", "agent", "real person", "talk to human"], "human_handoff", 0.9),
        ]
        for words, intent, conf in rules:
            if any(w in msg for w in words):
                return {"intent": intent, "confidence": conf, "entities": self._extract_dt(message), "action": "none"}
        if any(w in msg for w in ["interested", "buy", "purchase", "subscribe", "chahiye"]):
            return {"intent": "lead_enquiry", "confidence": 0.85, "entities": {}, "action": "save_lead"}
        return {"intent": "general_query", "confidence": 0.5, "entities": {}, "action": "none"}

    def _extract_dt(self, message: str) -> dict:
        entities = {}
        for p in [r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", r"(kal|aaj|parson|today|tomorrow)"]:
            m = re.search(p, message.lower())
            if m:
                entities["date"] = m.group(0)
                break
        for p in [r"(\d{1,2}):(\d{2})\s*(am|pm)?", r"(\d{1,2})\s*(am|pm|baje)"]:
            m = re.search(p, message.lower())
            if m:
                entities["time"] = m.group(0)
                break
        return entities


class ResponseGenerator:
    """LLM-based contextual response generator with localised fallbacks."""

    def __init__(self):
        self.generation_llm = get_generation_llm()

    async def generate(self, intent: str, message: str, history: List[Dict],
                       contact: Optional[Dict] = None, vertical: str = "general",
                       lang: str = "en") -> str:
        vertical_context = self._get_vertical_context(vertical)
        context = ""
        if history:
            context = "\n".join([
                f"{'User' if h['direction'] == 'incoming' else 'Bot'}: {h['content']}"
                for h in history[-5:]
            ])

        skill_prompt = ""
        try:
            from skills.loader import build_prompt as skill_build_prompt
            skill_prompt = skill_build_prompt(vertical, message) or ""
        except Exception:
            skill_prompt = ""

        lang_instruction = (
            f"Respond in {lang}." if lang != "en"
            else "Respond in Hinglish (Hindi + English mix) - casual, friendly, professional."
        )
        prompt = f"""You are a helpful WhatsApp AI assistant for a {vertical} business.
{lang_instruction}

{vertical_context}

Previous conversation:
{context}

{skill_prompt}

User's intent: {intent}
User message: {message}

Generate a helpful, contextual response. Keep it concise (2-3 lines max).
Use emojis appropriately. If the user needs more info (date, time, name), ask for it.

Response:"""

        try:
            if self.generation_llm is not None and hasattr(self.generation_llm, 'invoke'):
                response = await asyncio.to_thread(self.generation_llm.invoke, prompt)
                reply = response.content if hasattr(response, 'content') else str(response)
                return reply.strip()
        except Exception as e:
            logger.warning("LLM response generation failed: %s", e)

        # Localised fallback keeps the conversation going even when the LLM is down.
        return localize(intent, lang)

    def _get_vertical_context(self, vertical: str) -> str:
        contexts = {
            "general": "You are a helpful WhatsApp AI assistant for Indian businesses.",
            "doctor": "You are a medical clinic assistant. Help with appointments, symptoms, prescriptions, lab reports. Add an AI disclaimer.",
            "lawyer": "You are a legal assistant. Help with case consultations, documents, appointments. Add an AI disclaimer.",
            "ca": "You are a CA/accountant assistant. Help with ITR filing, GST returns, tax deadlines, document collection.",
            "restaurant": "You are a restaurant assistant. Help with table bookings, menu queries, order status.",
            "salon": "You are a salon assistant. Help with service bookings, stylist appointments, pricing.",
        }
        return contexts.get(vertical, contexts["general"])


class ContextLoader:
    """
    Rolling-summary context loader for the orchestrator.

    Instead of sending the *entire* conversation history to the LLM on every
    turn, the ContextLoader keeps:

    * a **rolling summary** of all turns that fall outside the active window,
      refreshed every time the window slides.
    * the last ``max_active_turns`` (default 5) most recent turns in full.

    The summary + active window is what gets passed to the prompt as
    ``context``, capping the token footprint while preserving conversational
    coherence.

    Summaries are cached per (client_id, phone_number) so re-summarisation only
    happens when new content arrives.
    """

    DEFAULT_MAX_TURNS = 5

    def __init__(self, max_active_turns: int = DEFAULT_MAX_TURNS):
        self.max_active_turns = max_active_turns
        # {cache_key: {"summary": str, "turns": list, "last_index": int}}
        self._cache: Dict[str, dict] = {}
        self._generation_llm = None
        try:
            from model_router import get_generation_llm
            self._generation_llm = get_generation_llm()
        except Exception:
            pass

    def _cache_key(self, phone_number: str, client_id: int) -> str:
        return f"{client_id}:{phone_number}"

    def _format_turn(self, h: dict) -> str:
        role = "User" if h.get("direction") == "incoming" else "Bot"
        return f"{role}: {h.get('content', '')}"

    async def summarize(self, history_dicts: List[dict]) -> str:
        """Produce a concise narrative summary of turns that fall outside the window."""
        if len(history_dicts) <= self.max_active_turns:
            return ""
        # Use the LLM for a proper summary; fall back to a truncated join.
        excluded = history_dicts[:-self.max_active_turns] if self.max_active_turns > 0 else history_dicts
        if not excluded:
            return ""
        text_block = "\n".join(
            f"[{h.get('created_at', '?')}] {self._format_turn(h)}" for h in excluded
        )
        if self._generation_llm is None:
            return text_block[:500] + "..." if len(text_block) > 500 else text_block
        prompt = (
            "Summarise the following WhatsApp conversation turns into a single "
            "concise paragraph (max 3 sentences). Do not include verbatim messages:\n\n"
            f"{text_block}\n\nSummary:"
        )
        try:
            import asyncio as _aio
            response = await _aio.to_thread(self._generation_llm.invoke, prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return content.strip()[:1000]
        except Exception as e:
            logger.warning("LLM summary failed, using truncated text: %s", e)
            return text_block[:500] + "..." if len(text_block) > 500 else text_block

    async def load_context(self, phone_number: str, client_id: int,
                           history_dicts: List[dict]) -> str:
        """
        Build the ``context`` string passed to downstream LLM prompts.

        Returns the rolling summary followed by the last ``max_active_turns``
        turns in full.
        """
        key = self._cache_key(phone_number, client_id)
        cache = self._cache.get(key)
        active = history_dicts[-self.max_active_turns:]

        # Only re-summarise when new content has been appended since the last call.
        last_seen = cache.get("last_count", -1) if cache else -1
        if cache and len(history_dicts) == last_seen:
            # No new turns → reuse cached summary
            summary = cache.get("summary", "")
        else:
            summary = await self.summarize(history_dicts) if len(history_dicts) > self.max_active_turns else ""

        self._cache[key] = {
            "summary": summary,
            "turns": active,
            "last_count": len(history_dicts),
        }

        parts = []
        if summary:
            parts.append(f"[Rolling summary: {summary}]")
        if active:
            parts.append("\n".join(self._format_turn(h) for h in active))
        return "\n".join(parts)

    def evict(self, phone_number: str, client_id: int) -> None:
        """Clear cached context for a conversation (e.g. on human handoff)."""
        key = self._cache_key(phone_number, client_id)
        self._cache.pop(key, None)


class AgentOrchestrator:
    """Main orchestrator routing messages through the Manager Agent multi-agent system."""

    def __init__(self):
        self.vertical_name = "general"
        self._vertical_cache: dict = {}
        self._manager_agents: dict = {}  # per-client_id manager agents (business-aware)

    def _biz_system_prompt(self, ctx: dict) -> str:
        """Build the 'speak-as-the-business' persona from the profile context."""
        try:
            from cli_commands import build_business_system_prompt
            return build_business_system_prompt(ctx)
        except Exception as e:
            logger.debug("business persona prompt build failed: %s", e)
            return ""

    def _get_manager_agent(self, client_id: int = 1):
        profile = self._biz_profile(client_id)
        biz_name = (profile or {}).get("name") or "Our Business"
        cached = self._manager_agents.get(client_id)
        if cached is not None and cached[0] == biz_name:
            return cached[1]
        try:
            from agents.manager import get_manager_agent
            agent = get_manager_agent(business_name=biz_name)
            self._manager_agents[client_id] = (biz_name, agent)
            if profile:
                logger.info("Manager Agent initialised for business '%s' (client %s)", biz_name, client_id)
            return agent
        except Exception as e:
            logger.warning("Manager Agent not available: %s", e)
            return None

    def _biz_profile(self, client_id: int):
        """Full business profile dict for a client (or None)."""
        try:
            from business_profiles import business_manager
            for p in business_manager.profiles.values():
                if p.client_id == int(client_id):
                    btype = p.business_type.value if hasattr(p.business_type, "value") else str(p.business_type)
                    ctx = {
                        "name": p.name,
                        "business_type": btype,
                        "description": getattr(p, "description", "") or "",
                        "working_hours": getattr(p, "working_hours", None) or getattr(p, "business_hours", "") or "",
                        "address": getattr(p, "address", "") or "",
                        "phone": getattr(p, "contact_phone", "") or "",
                        "email": getattr(p, "contact_email", "") or "",
                        "website": getattr(p, "website", "") or "",
                        "payment_methods": getattr(p, "payment_methods", []) or [],
                        "delivery": getattr(p, "delivery_enabled", None),
                        "currency": getattr(p, "currency", "INR") or "INR",
                        "language": getattr(p, "language", "") or "",
                        "welcome_message": getattr(p, "welcome_message", "") or "",
                    }
                    try:
                        items = business_manager.get_catalog(p.id) or []
                        if items:
                            ctx["catalog"] = [
                                {"name": i.get("name"), "price": i.get("price"),
                                 "category": i.get("category"), "available": i.get("is_available", True)}
                                for i in items[:50]
                            ]
                    except Exception:
                        pass
                    # Canonical aliases so the persona builder recognises them
                    ctx.setdefault("contact_phone", ctx.get("phone", ""))
                    ctx.setdefault("contact_email", ctx.get("email", ""))
                    ctx.setdefault("delivery_enabled", ctx.get("delivery") is True)
                    ctx["system_prompt"] = self._biz_system_prompt(ctx)
                    return ctx
        except Exception:
            return None
        return None

    async def _load_vertical(self, client_id: int) -> str:
        if client_id in self._vertical_cache:
            return self._vertical_cache[client_id]
        try:
            try:
                from business_profiles import business_manager
                for p in business_manager.profiles.values():
                    if p.client_id == int(client_id):
                        vertical = p.business_type.value if hasattr(p.business_type, 'value') else str(p.business_type)
                        self._vertical_cache[client_id] = vertical
                        return vertical
            except Exception:
                pass
            if DB_OK:
                async for session in get_session():
                    from sqlalchemy import select
                    from db import Client
                    result = await session.execute(select(Client).where(Client.id == int(client_id)))
                    client = result.scalar_one_or_none()
                    if client:
                        vertical = client.vertical or "general"
                        self._vertical_cache[client_id] = vertical
                        return vertical
        except Exception as e:
            logger.warning("Failed to load vertical for client %s: %s", client_id, e)
        return "general"

    async def process_message(self, phone_number: str, message: str, client_id: int = 1,
                              media_data: Optional[bytes] = None,
                              media_mimetype: Optional[str] = None) -> str:
        """Process an incoming message and return the assistant reply."""
        from metrics import metrics_collector
        from usage_metering import usage_meter

        lang = detect_language(message)
        bind_context(client_id=client_id, phone_number=phone_number, language=lang)

        metrics_collector.record_message("incoming", client_id)
        await usage_meter.record_usage(client_id, "messages_received", 1)
        log_metric("message.received", 1, {"client_id": client_id, "direction": "incoming"})

        self.vertical_name = await self._load_vertical(client_id)

        if not DB_OK:
            return localize("general_query", lang)

        async for session in get_session():
            await save_message(session, phone_number, message, direction="incoming", client_id=client_id)

            # ── Subscription gate: skip the AI entirely for inactive clients ──
            from sqlalchemy import select as _sa_select
            from db import Client as _Client
            cres = await session.execute(
                _sa_select(_Client.is_active).where(_Client.id == int(client_id)))
            active = cres.scalar_one_or_none()
            if active is False:
                logger.info("client %s is inactive (subscription off) - AI skipped for %s",
                            client_id, phone_number)
                return ("This business's AI assistant is temporarily offline. "
                        "Please contact the business owner directly.")

            history = await get_conversation_history(session, phone_number, limit=10, client_id=client_id)
            history_dicts = [{"content": h.content, "direction": h.direction,
                              "created_at": h.created_at.isoformat()} for h in history]
            contact = await upsert_contact(session, phone_number=phone_number, client_id=client_id)
            contact_dict = {"name": contact.name, "phone": contact.phone_number}

            sm = _safe_call(get_state_machine) if get_state_machine else None
            if sm is not None and hasattr(sm, 'is_human_takeover'):
                if await sm.is_human_takeover(client_id, phone_number):
                    logger.info("human takeover active for %s", phone_number)
                    return ""

            # ── Instant fast path (Phase 1-4): complete Hinglish bookings/orders
            #    skip the multi-second LLM loop entirely.
            try:
                from services.instant_actions import try_instant_action
                instant_reply, _slots = await try_instant_action(
                    phone_number, message, client_id, self._biz_profile(client_id))
                if instant_reply:
                    logger.info("instant action handled message for %s (client %s)",
                                phone_number, client_id)
                    await self._finalize_turn(session, phone_number, message, instant_reply,
                                              client_id, sm, history_dicts, contact_dict,
                                              lang, metrics_collector, usage_meter)
                    return instant_reply
            except Exception as e:
                logger.warning("instant action path failed (falling through to agents): %s", e)

            # Try Manager Agent first
            manager_agent = self._get_manager_agent(client_id)
            if manager_agent is not None:
                try:
                    from agents.manager import ManagerInput
                    manager_input = ManagerInput(
                        client_id=client_id,
                        conversation_id=f"{phone_number}:{client_id}",
                        message_text=message,
                        vertical=self.vertical_name,
                        lang=lang,
                        phone_number=phone_number,
                        entity_snapshot=self._extract_entity_snapshot(contact_dict),
                        history=history_dicts,
                        has_open_task=False,
                        business_context=self._biz_profile(client_id) or {},
                    )
                    response = await manager_agent.handle(manager_input)
                    if response:
                        await self._finalize_turn(session, phone_number, message, response, client_id, sm, history_dicts, contact_dict, lang, metrics_collector, usage_meter)
                        return response
                except Exception as e:
                    logger.warning("Manager Agent failed, falling back to legacy flow: %s", e)

            # Try constraint-aware reply engine for product/catalog queries
            try:
                from services.constraint_reply_engine import generate_constraint_reply, detect_complaint
                if detect_complaint(message):
                    reason = "Complaint detected in message"
                    if request_handoff is not None:
                        await request_handoff(phone_number, reason, 0.0)
                    return localize("human_handoff", lang)

                constraint_reply = await generate_constraint_reply(
                    owner_id=client_id,
                    message=message,
                    language=lang,
                )
                if constraint_reply and "setting up" not in constraint_reply.lower():
                    await self._finalize_turn(session, phone_number, message, constraint_reply, client_id, sm, history_dicts, contact_dict, lang, metrics_collector, usage_meter)
                    return constraint_reply
            except Exception as e:
                logger.warning("Constraint engine failed, falling back to legacy flow: %s", e)

            # Fallback to legacy flow if Manager Agent is unavailable
            intent_result = await self.intent_detector.detect(message, history_dicts, lang)
            intent = intent_result["intent"]
            entities = intent_result.get("entities", {})
            action = intent_result.get("action", "none")
            logger.info("intent=%s confidence=%.2f lang=%s", intent, intent_result.get("confidence", 0), lang)

            if sm is not None:
                try:
                    if hasattr(sm, 'transition'):
                        new_state = await sm.transition(client_id, phone_number, intent, entities)
                    else:
                        new_state = sm.transition(phone_number, intent, entities)
                except Exception:
                    new_state = {"state": "browsing"}
            else:
                new_state = {"state": "browsing"}

            if intent == "human_handoff" or intent_result.get("confidence", 1.0) < 0.6:
                reason = "User requested human" if intent == "human_handoff" else f"Low confidence ({intent_result.get('confidence', 0):.2f})"
                if request_handoff is not None:
                    await request_handoff(phone_number, reason, intent_result.get("confidence", 0))
                return localize("human_handoff", lang)

            vertical_response = await self._route_to_vertical(intent, message, entities, contact_dict, client_id, lang)
            if vertical_response:
                response = vertical_response
            else:
                langchain_agent = self._try_langchain()
                if langchain_agent is not None and getattr(langchain_agent, "available", False):
                    try:
                        biz_context = self._biz_context(client_id)
                        response = await langchain_agent.generate_response(
                            message=message, history=history_dicts,
                            client_id=client_id, business_context=biz_context)
                    except Exception as e:
                        logger.warning("LangChain agent failed: %s", e)
                        response = await self.response_generator.generate(intent, message, history_dicts, contact_dict, self.vertical_name, lang)
                else:
                    response = await self.response_generator.generate(intent, message, history_dicts, contact_dict, self.vertical_name, lang)

            # Persist appointment when we have a date
            if intent == "appointment_booking" and entities.get("date"):
                try:
                    from db import Appointment
                    appt = Appointment(
                        client_id=client_id, phone_number=phone_number,
                        title=f"Appointment - {entities.get('date', 'TBD')}",
                        appointment_date=entities.get("date"),
                        appointment_time=entities.get("time", "TBD"),
                        status="scheduled")
                    session.add(appt)
                    await session.commit()
                    await usage_meter.record_usage(client_id, "appointments_booked", 1)
                    log_metric("appointment.booked", 1, {"client_id": client_id})
                    logger.info("appointment saved for %s (client %s)", phone_number, client_id)
                except Exception as e:
                    logger.warning("failed to save appointment: %s", e)

            if action == "save_lead" or intent == "lead_enquiry":
                await usage_meter.record_usage(client_id, "leads_processed", 1)
                log_metric("lead.processed", 1, {"client_id": client_id})

            # Estimate tokens used (rough heuristic ~4 chars/token) for metering
            est_tokens = max(1, len(message) // 4 + len(response) // 4)
            await usage_meter.record_usage(client_id, "tokens_used", est_tokens)
            metrics_collector.record_llm_latency(0.0, "orchestrator", client_id)
            log_metric("llm.tokens", est_tokens, {"client_id": client_id})

            await save_message(session, phone_number, response, direction="outgoing", client_id=client_id)
            metrics_collector.record_message("outgoing", client_id)
            await usage_meter.record_usage(client_id, "messages_sent", 1)
            log_metric("message.sent", 1, {"client_id": client_id, "direction": "outgoing"})

            try:
                if sm is not None and hasattr(sm, 'set_state'):
                    await sm.set_state(client_id, phone_number,
                                       state=new_state.get("state", "browsing") if isinstance(new_state, dict) else "browsing",
                                       intent=intent, entities=entities, slot_data=entities)
            except Exception as e:
                logger.warning("session save failed: %s", e)

            return response

    # Backwards-compatible alias used by some callers/tests.
    async def process_incoming_message(self, phone_number: str, message: str, client_id: int = 1,
                                       media_data=None, media_mimetype=None) -> str:
        return await self.process_message(phone_number, message, client_id, media_data, media_mimetype)

    # -- helpers ------------------------------------------------------------

    def _try_langchain(self):
        try:
            from langchain_agent import langchain_agent
            return langchain_agent
        except Exception:
            return None

    def _biz_context(self, client_id: int):
        return self._biz_profile(client_id)

    async def _route_to_vertical(self, intent, message, entities, contact, client_id, lang="en"):
        vertical = self.vertical_name
        try:
            if intent in ("menu_inquiry", "pricing_query", "order_placement"):
                catalog_reply = await self._catalog_lookup(message, client_id)
                if catalog_reply:
                    return catalog_reply
            routes = {
                "ca": ("verticals.ca", "CAAccountantBot"),
                "lawyer": ("verticals.lawyer", "LawyerBot"),
                "mba": ("verticals.mba", "MBABot"),
                "doctor": ("verticals.doctor", "DoctorClinicBot"),
                "restaurant": ("verticals.restaurant", "RestaurantBot"),
            }
            if vertical in routes:
                module_name, cls_name = routes[vertical]
                mod = __import__(module_name, fromlist=[cls_name])
                bot = getattr(mod, cls_name)()
                return bot.get_response(intent, message, entities, name=contact.get("name"))
        except Exception as e:
            logger.warning("vertical routing error (%s): %s", vertical, e)
        return None

    async def _catalog_lookup(self, message: str, client_id: int):
        try:
            from business_profiles import business_manager
            profile = None
            for p in business_manager.profiles.values():
                if p.client_id == int(client_id):
                    profile = p
                    break
            if not profile:
                return None
            items = business_manager.get_catalog(profile.id)
            if not items:
                return None
            msg_l = message.lower()
            for item in items:
                if item["name"].lower() in msg_l:
                    avail = "Available ✅" if item["is_available"] else "Out of stock ❌"
                    return (f"📦 {item['name']}\n💰 Price: ₹{item['price']}\n"
                            f"📂 Category: {item['category']}\n📊 Status: {avail}\n\n"
                            f"Order karna hai toh 'order {item['name']}' batao!")
            if any(w in msg_l for w in ["menu", "catalog", "list", "kya available", "items"]):
                lines = ["📋 Humara Menu:\n"]
                for item in items:
                    if item["is_available"]:
                        lines.append(f"• {item['name']} — ₹{item['price']}")
                lines.append("\nKisi item ka naam batao price ke liye!")
                return "\n".join(lines)
        except Exception as e:
            logger.warning("catalog lookup error: %s", e)
        return None

    def _extract_entity_snapshot(self, contact: Dict) -> Dict[str, Any]:
        """Extract entity snapshot from contact dict."""
        if not contact:
            return {}
        return {k: v for k, v in contact.items() if v and k not in ("id", "created_at", "updated_at")}

    async def _finalize_turn(self, session, phone_number, message, response, client_id, sm, history_dicts, contact_dict, lang, metrics_collector, usage_meter):
        """Persist response, update state machine, and record metrics."""
        from usage_metering import usage_meter

        # Estimate tokens
        est_tokens = max(1, len(message) // 4 + len(response) // 4)
        await usage_meter.record_usage(client_id, "tokens_used", est_tokens)
        metrics_collector.record_llm_latency(0.0, "orchestrator", client_id)
        log_metric("llm.tokens", est_tokens, {"client_id": client_id})

        await save_message(session, phone_number, response, direction="outgoing", client_id=client_id)
        metrics_collector.record_message("outgoing", client_id)
        await usage_meter.record_usage(client_id, "messages_sent", 1)
        log_metric("message.sent", 1, {"client_id": client_id, "direction": "outgoing"})

        try:
            if sm is not None and hasattr(sm, 'set_state'):
                await sm.set_state(client_id, phone_number,
                                   state="browsing",
                                   intent="", entities={}, slot_data={})
        except Exception as e:
            logger.warning("session save failed: %s", e)


# Module-level singleton used by main.py via app.state.orchestrator
orchestrator = AgentOrchestrator()
