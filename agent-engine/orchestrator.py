"""
Agent Orchestrator - Uses LLM for intent detection and response generation
"""
import json
import re
from typing import Optional, List, Dict, Any
import asyncio
from datetime import datetime

from db import get_session, save_message, get_conversation_history, upsert_contact, Appointment
from llm_setup import get_llm
from config import settings
from state_machine import get_state_machine
from handoff import request_handoff

try:
    from langchain_agent import langchain_agent
    LANGCHAIN_ENABLED = True
except ImportError:
    LANGCHAIN_ENABLED = False
    print("[i] LangChain agent not available, using built-in AI")

try:
    from skills.loader import build_prompt as skill_build_prompt
    SKILLS_AVAILABLE = True
except ImportError:
    SKILLS_AVAILABLE = False
    print("[i] Skills loader not available")


class IntentDetector:
    """Uses LLM to detect user intent from message and extract structured entities"""

    def __init__(self):
        self.llm = get_llm()

    async def detect(self, message: str, history: List[Dict]) -> dict:
        """
        Use LLM to detect intent and extract entities.
        Falls back to keyword matching if LLM fails.
        Returns structured data: intent, confidence, entities, action
        """
        # Build conversation context
        context = ""
        if history:
            context = "\n".join([f"{'User' if h['direction'] == 'incoming' else 'Bot'}: {h['content']}" 
                                for h in history[-5:]])

        prompt = f"""You are an intent classifier for a WhatsApp AI assistant for Indian businesses.
Analyze the user message and classify it into ONE of these intents:

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
- date: Any date mentioned (kal, aaj, tomorrow, DD/MM/YYYY, etc.)
- time: Any time mentioned (3 baje, 5:30 pm, etc.)
- person_name: Person's name if mentioned
- location: City/location if mentioned
- product_name: Product or service name if mentioned
- quantity: Number of items/people if mentioned
- phone_number: Phone number if mentioned

Return ONLY valid JSON (no markdown, no extra text):
{{"intent": "intent_name", "confidence": 0.95, "entities": {{"date": "", "time": "", "person_name": "", "location": "", "product_name": "", "quantity": "", "phone_number": ""}}, "action": "create_order|create_appointment|save_lead|send_info|none"}}

Previous conversation:
{context}

User message: {message}

JSON response:"""

        try:
            # Try LLM-based detection (wrapped in to_thread to avoid blocking event loop)
            if hasattr(self.llm, 'invoke'):
                response = await asyncio.to_thread(self.llm.invoke, prompt)
                result_text = response.content if hasattr(response, 'content') else str(response)
                
                # Extract JSON from response
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                    return {
                        "intent": result.get("intent", "general_query"),
                        "confidence": result.get("confidence", 0.7),
                        "entities": result.get("entities", {}),
                        "action": result.get("action", "none")
                    }
        except Exception as e:
            print(f"[!] LLM intent detection failed: {e}, falling back to keywords")

        # Fallback to keyword-based detection
        return self._keyword_fallback(message)

    def _keyword_fallback(self, message: str) -> dict:
        """Fallback keyword-based intent detection"""
        msg = message.lower()
        
        if any(w in msg for w in ["hello", "hi", "hey", "namaste", "namaskar"]):
            return {"intent": "greeting", "confidence": 0.9, "entities": {}}
        if any(w in msg for w in ["bye", "goodbye", "alvida", "dhanyavad", "thank"]):
            return {"intent": "farewell", "confidence": 0.9, "entities": {}}
        if any(w in msg for w in ["appointment", "book", "schedule", "meeting", "slot", "visit", "table"]):
            return {"intent": "appointment_booking", "confidence": 0.85, "entities": self._extract_dt(message)}
        if any(w in msg for w in ["price", "cost", "rate", "kitna", "charges", "fees"]):
            return {"intent": "pricing_query", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["help", "support", "problem", "issue", "error"]):
            return {"intent": "support", "confidence": 0.8, "entities": {}}
        if any(w in msg for w in ["fever", "cough", "cold", "headache", "pain", "bukhar", "khansi"]):
            return {"intent": "symptom_check", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["prescription", "dawai", "medicine"]):
            return {"intent": "prescription_request", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["lab", "report", "test", "blood"]):
            return {"intent": "lab_report", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["case", "court", "legal", "mukadma", "property dispute", "divorce"]):
            return {"intent": "case_inquiry", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["itr", "tax", "gst", "income tax", "deadline"]):
            return {"intent": "itr_inquiry", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["menu", "food", "khana", "order"]):
            return {"intent": "menu_inquiry", "confidence": 0.85, "entities": {}}
        if any(w in msg for w in ["pay", "payment", "razorpay", "upi", "paisa", "bhugtan"]):
            return {"intent": "payment_request", "confidence": 0.85, "entities": {}}
        
        return {"intent": "general_query", "confidence": 0.5, "entities": {}}

    def _extract_dt(self, message: str) -> dict:
        """Extract date/time from message"""
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
    """Uses LLM to generate contextual responses"""

    def __init__(self):
        self.llm = get_llm()

    async def generate(self, intent: str, message: str, history: List[Dict], 
                       contact: Optional[Dict] = None, vertical: str = "general") -> str:
        """Generate response using LLM with context"""
        
        # Get vertical-specific context
        vertical_context = self._get_vertical_context(vertical)
        
        # Build conversation history
        context = ""
        if history:
            context = "\n".join([f"{'User' if h['direction'] == 'incoming' else 'Bot'}: {h['content']}" 
                                for h in history[-5:]])

        # Try to augment with skills if available
        skill_prompt = ""
        if SKILLS_AVAILABLE:
            try:
                skill_prompt = skill_build_prompt(vertical, message) or ""
            except Exception as e:
                print(f"[!] Skill prompt build failed: {e}")

        prompt = f"""You are a helpful WhatsApp AI assistant for a {vertical} business.
You respond in Hinglish (Hindi + English mix) - casual, friendly, and professional.

{vertical_context}

Previous conversation:
{context}

{skill_prompt}

User's intent: {intent}
User message: {message}

Generate a helpful, contextual response in Hinglish. Keep it concise (2-3 lines max).
Use emojis appropriately. If the user needs to provide more info (date, time, name), ask for it.

Response:"""

        try:
            # Try LLM-generated response (wrapped in to_thread to avoid blocking event loop)
            if hasattr(self.llm, 'invoke'):
                response = await asyncio.to_thread(self.llm.invoke, prompt)
                reply = response.content if hasattr(response, 'content') else str(response)
                return reply.strip()
        except Exception as e:
            print(f"[!] LLM response generation failed: {e}, using template")

        # Fallback to template
        return self._template_fallback(intent, message, vertical)

    def _get_vertical_context(self, vertical: str) -> str:
        """Get vertical-specific context for the LLM"""
        contexts = {
            "general": "You are a helpful WhatsApp AI assistant for Indian businesses.",
            "doctor": "You are a medical clinic assistant. You help with appointments, symptoms, prescriptions, and lab reports. Always add disclaimer that you're AI, not a doctor.",
            "lawyer": "You are a legal assistant. You help with case consultations, legal documents, and appointments. Always add disclaimer that you're AI, not a lawyer.",
            "ca": "You are a CA/accountant assistant. You help with ITR filing, GST returns, tax deadlines, and document collection.",
            "restaurant": "You are a restaurant assistant. You help with table bookings, menu queries, and order status.",
            "salon": "You are a salon assistant. You help with service bookings, stylist appointments, and pricing."
        }
        return contexts.get(vertical, contexts["general"])

    def _template_fallback(self, intent: str, message: str, vertical: str) -> str:
        """Fallback template responses if LLM fails"""
        templates = {
            "greeting": f"Namaste! 👋 Main aapka {vertical} assistant hoon. Main aapki kaise madad kar sakta hoon?",
            "appointment_booking": "Ji, appointment book karne ke liye kya aap date aur time bata sakte hain?",
            "pricing_query": "Pricing ke baare mein jaankari ke liye, kya aap bata sakte hain ki aapko kis service mein interest hai?",
            "support": "Mujhe aapki problem samajhne mein khushi hogi. Kya aap thoda detail mein bata sakte hain?",
            "farewell": "Dhanyavad! 🙏 Koi aur madad chahiye toh bataiye.",
            "symptom_check": "Kya aap apne symptoms detail mein bata sakte hain? Emergency hai toh 108 dial karein!",
            "prescription_request": "Prescription renewal ke liye purani prescription ki photo bheje.",
            "lab_report": "Lab reports ke liye report ki photo/PDF bhej sakte hain.",
            "case_inquiry": "Kya aap case ke baare mein thoda aur bata sakte hain?",
            "itr_inquiry": "ITR filing ke liye main aapki madad kar sakta hoon. Kya aap bata sakte hain ki aapki income source kya hai?",
            "menu_inquiry": "Humare menu mein veg aur non-veg dono options hain. Kya aap kuch specific dekhna chahenge?",
            "document_request": "Ji, aap document upload kar sakte hain. Bas file forward karein.",
            "lead_enquiry": "Bahut achha! Aap humari services mein interest dikha rahe hain. Kya aap apna naam aur city bata sakte hain?",
            "payment_request": "Payment ke liye main aapko link bhej sakta hoon. Kitni amount hai? 💳",
            "general_query": f"Main samajh gaya. Aapne kaha: '{message}'. Main aapki kaise madad kar sakta hoon?"
        }
        return templates.get(intent, templates["general_query"])


class AgentOrchestrator:
    """Main orchestrator that wires everything together"""

    def __init__(self):
        self.intent_detector = IntentDetector()
        self.response_generator = ResponseGenerator()
        self.vertical_name = "general"
        self._vertical_cache: dict = {}

    async def _load_vertical(self, client_id: int) -> str:
        """Load business vertical from DB for this client."""
        if client_id in self._vertical_cache:
            return self._vertical_cache[client_id]
        try:
            # First check business_manager (profiles created via API)
            try:
                from business_profiles import business_manager
                for p in business_manager.profiles.values():
                    if p.client_id == int(client_id):
                        vertical = p.business_type.value if hasattr(p.business_type, 'value') else str(p.business_type)
                        self._vertical_cache[client_id] = vertical
                        return vertical
            except Exception as e:
                print(f"[!] business_manager lookup failed: {e}")

            # Fallback: check Client table
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
            print(f"[!] Failed to load vertical for client {client_id}: {e}")
        return "general"

    async def process_message(self, phone_number: str, message: str, client_id: int = 1) -> str:
        """
        Main entry point for processing incoming WhatsApp messages.
        1. Save incoming message
        2. Get conversation history
        3. Detect intent using LLM
        4. Generate response using LLM
        5. Save outgoing message
        6. Return response
        """
        # Load vertical from DB instead of hardcoded "general"
        self.vertical_name = await self._load_vertical(client_id)

        async for session in get_session():
            # Save incoming message (scoped to client_id)
            await save_message(session, phone_number, message, direction="incoming", client_id=client_id)

            # Get conversation history for context (scoped to client_id)
            history = await get_conversation_history(session, phone_number, limit=10, client_id=client_id)
            history_dicts = [{"content": h.content, "direction": h.direction, "created_at": h.created_at.isoformat()} 
                           for h in history]

            # Get or create contact (scoped to client_id)
            contact = await upsert_contact(session, phone_number=phone_number, client_id=client_id)
            contact_dict = {"name": contact.name, "phone": contact.phone_number}

            # Check if human is handling this conversation
            sm = get_state_machine()
            if sm.is_human_takeover(phone_number):
                print(f"[i] Human takeover active for {phone_number}")
                return ""

            # Detect intent using LLM
            intent_result = await self.intent_detector.detect(message, history_dicts)
            intent = intent_result["intent"]
            entities = intent_result.get("entities", {})
            action = intent_result.get("action", "none")

            print(f"[i] Intent: {intent} (confidence: {intent_result.get('confidence', 0):.2f})")

            # Update state machine
            sm = get_state_machine()
            new_state = sm.transition(phone_number, intent, entities)
            state_prompt = sm.get_state_prompt(phone_number)
            print(f"[i] State: {new_state['state']}")

            # Trigger handoff if confidence is low or user explicitly asks
            if intent == "human_handoff" or intent_result.get("confidence", 1.0) < 0.6:
                reason = "User requested human" if intent == "human_handoff" else f"Low confidence ({intent_result.get('confidence', 0):.2f})"
                await request_handoff(phone_number, reason, intent_result.get("confidence", 0))
                return "Main abhi thoda confused hoon. Ek human agent aapki help karenge. Thoda ruk jaiye! 🙏"

            # Route to vertical-specific handler if available
            vertical_response = await self._route_to_vertical(intent, message, entities, contact_dict, client_id)
            if vertical_response:
                response = vertical_response
            else:
                # Try LangChain agent first (with knowledge base retrieval)
                if LANGCHAIN_ENABLED and langchain_agent.available:
                    try:
                        # Load business context for the agent
                        biz_context = None
                        try:
                            from business_profiles import business_manager
                            for p in business_manager.profiles.values():
                                if p.client_id == int(client_id):
                                    biz_context = {
                                        "name": p.name,
                                        "business_type": p.business_type.value if hasattr(p.business_type, 'value') else str(p.business_type),
                                    }
                                    break
                        except Exception:
                            pass

                        response = await langchain_agent.generate_response(
                            message=message,
                            history=history_dicts,
                            client_id=client_id,
                            business_context=biz_context
                        )
                    except Exception as e:
                        print(f"[!] LangChain agent failed, falling back: {e}")
                        response = await self.response_generator.generate(
                            intent=intent,
                            message=message,
                            history=history_dicts,
                            contact=contact_dict,
                            vertical=self.vertical_name
                        )
                else:
                    # Fallback to built-in LLM response generator
                    response = await self.response_generator.generate(
                        intent=intent,
                        message=message,
                        history=history_dicts,
                        contact=contact_dict,
                        vertical=self.vertical_name
                    )

            # Handle appointment booking - save to DB if we have date/time
            if intent == "appointment_booking" and entities.get("date"):
                try:
                    from db import Appointment
                    appointment = Appointment(
                        client_id=client_id,
                        phone_number=phone_number,
                        title=f"Appointment - {entities.get('date', 'TBD')}",
                        appointment_date=entities.get("date"),
                        appointment_time=entities.get("time", "TBD"),
                        status="scheduled"
                    )
                    session.add(appointment)
                    await session.commit()
                    print(f"[v] Appointment saved for {phone_number} (client {client_id})")
                except Exception as e:
                    print(f"[!] Failed to save appointment: {e}")

            # Save outgoing message
            await save_message(session, phone_number, response, direction="outgoing")

            return response

    async def _route_to_vertical(self, intent: str, message: str, entities: dict, contact: dict, client_id: int):
        """Route to vertical-specific bot if available. Returns response string or None."""
        vertical = self.vertical_name
        try:
            # Catalog/inventory lookup for menu & pricing queries
            if intent in ("menu_inquiry", "pricing_query", "order_placement"):
                catalog_reply = await self._catalog_lookup(message, client_id)
                if catalog_reply:
                    return catalog_reply

            if vertical == "ca":
                from verticals.ca import CAAccountantBot
                bot = CAAccountantBot()
                return bot.get_response(intent, message, entities, name=contact.get("name"))
            elif vertical == "lawyer":
                from verticals.lawyer import LawyerBot
                bot = LawyerBot()
                return bot.get_response(intent, message, entities, name=contact.get("name"))
            elif vertical == "mba":
                from verticals.mba import MBABot
                bot = MBABot()
                return bot.get_response(intent, message, entities, name=contact.get("name"))
            elif vertical == "doctor":
                from verticals.doctor import DoctorClinicBot
                bot = DoctorClinicBot()
                return bot.get_response(intent, message, entities, name=contact.get("name"))
            elif vertical == "restaurant":
                from verticals.restaurant import RestaurantBot
                bot = RestaurantBot()
                return bot.get_response(intent, message, entities, name=contact.get("name"))
        except Exception as e:
            print(f"[!] Vertical routing error ({vertical}): {e}")
        return None

    async def _catalog_lookup(self, message: str, client_id: int):
        """Look up real catalog/inventory data for menu & pricing queries."""
        try:
            from business_profiles import business_manager
            # Find business profile for this client
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
            # Search for matching item by name
            for item in items:
                if item["name"].lower() in msg_l:
                    price = item["price"]
                    avail = "Available ✅" if item["is_available"] else "Out of stock ❌"
                    return (f"📦 {item['name']}\n"
                            f"💰 Price: ₹{price}\n"
                            f"📂 Category: {item['category']}\n"
                            f"📊 Status: {avail}\n\n"
                            f"Order karna hai toh 'order {item['name']}' batao!")

            # If user asks for menu/catalog, list all items
            if any(w in msg_l for w in ["menu", "catalog", "list", "kya available", "kya hai", "items"]):
                lines = ["📋 Humara Menu:\n"]
                for item in items:
                    if item["is_available"]:
                        lines.append(f"• {item['name']} — ₹{item['price']}")
                lines.append("\nKisi item ka naam batao price ke liye!")
                return "\n".join(lines)
        except Exception as e:
            print(f"[!] Catalog lookup error: {e}")
        return None
