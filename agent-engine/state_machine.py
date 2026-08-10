"""
Redis-backed State Machine - persistent conversation state
"""
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import json

# ---------------------------------------------------------------------------
# State Machine States
# ---------------------------------------------------------------------------

class ConversationState(Enum):
    """Possible conversation states"""
    BROWSING = "browsing"
    INQUIRING = "inquiring"
    DATE_REQUESTED = "date_requested"
    CONFIRMING = "confirming"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    COMPLETED = "completed"
    HUMAN_TAKEOVER = "human_takeover"
    CANCELLED = "cancelled"
    RESET = "reset"

    def to_string(self):
        return self.value


# ---------------------------------------------------------------------------
# In-Memory Fallback State Machine
# ---------------------------------------------------------------------------

class InMemoryStateMachine:
    """Fallback in-memory state machine when Redis is unavailable."""

    def __init__(self):
        self._states = {}
        self._available = False

    def get_state(self, phone_number: str) -> Dict[str, Any]:
        return self._states.get(phone_number, {
            "state": "browsing", "intent": "", "entities": {}, "context": {}
        })

    def set_state(self, phone_number: str, state, intent=None, entities=None, context=None) -> Dict[str, Any]:
        current = self.get_state(phone_number)
        current["state"] = state.value if hasattr(state, 'value') else state
        if intent:
            current["intent"] = intent
        if entities:
            current["entities"] = entities
        if context:
            current["context"].update(context)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._states[phone_number] = current
        return current

    def transition(self, phone_number: str, intent: str, entities: Dict) -> Dict[str, Any]:
        return self.get_state(phone_number)

    def get_state_prompt(self, phone_number: str) -> str:
        return ""

    def is_human_takeover(self, phone_number: str) -> bool:
        return False

    def reset(self, phone_number: str):
        self._states.pop(phone_number, None)


# ---------------------------------------------------------------------------
# Redis State Machine
# ---------------------------------------------------------------------------

class RedisStateMachine:
    """Redis-backed state machine for conversation state management"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0",
                 redis_db: int = 0,
                 prefix: str = "whatsapp_state:"):
        self._available = False
        self.redis = None
        try:
            import redis as redis_module
            self.redis = redis_module.from_url(redis_url, db=redis_db, socket_connect_timeout=1)
            self.redis.ping()
            self._available = True
        except Exception:
            self._available = False
        self.prefix = prefix
        self.ttl = 2592000

    def _get_key(self, phone_number: str) -> str:
        return f"{self.prefix}{phone_number}"

    def get_state(self, phone_number: str) -> Dict[str, Any]:
        if not self._available:
            return {"state": "browsing", "intent": "", "entities": {}, "context": {}}
        try:
            key = self._get_key(phone_number)
            data = self.redis.get(key)
            if data:
                return json.loads(data)
        except Exception:
            self._available = False
        return {"state": "browsing", "intent": "", "entities": {}, "context": {}}

    def set_state(self, phone_number: str, state, intent=None, entities=None, context=None) -> Dict[str, Any]:
        current = self.get_state(phone_number)
        current["state"] = state.value if hasattr(state, 'value') else state
        if intent:
            current["intent"] = intent
        if entities:
            current["entities"] = entities
        if context:
            current["context"].update(context)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self._available:
            try:
                key = self._get_key(phone_number)
                self.redis.setex(key, self.ttl, json.dumps(current))
            except Exception:
                self._available = False
        return current

    def transition(self, phone_number: str, intent: str, entities: Dict) -> Dict[str, Any]:
        current = self.get_state(phone_number)
        current_state = current["state"]

        if intent == "human_handoff":
            return self.set_state(phone_number, ConversationState.HUMAN_TAKEOVER, intent, entities)

        if current_state == ConversationState.BROWSING.value:
            if intent in ["appointment_booking", "order_placement", "pricing_query"]:
                return self.set_state(phone_number, ConversationState.INQUIRING, intent, entities)

        elif current_state == ConversationState.INQUIRING.value:
            if intent == "appointment_booking" and entities.get("date"):
                return self.set_state(phone_number, ConversationState.CONFIRMING, intent, entities)
            elif intent == "order_placement" and entities.get("product_name"):
                return self.set_state(phone_number, ConversationState.CONFIRMING, intent, entities)
            elif intent == "payment_request":
                return self.set_state(phone_number, ConversationState.AWAITING_PAYMENT, intent, entities)

        elif current_state == ConversationState.CONFIRMING.value:
            if intent == "payment_request":
                return self.set_state(phone_number, ConversationState.AWAITING_PAYMENT, intent, entities)
            elif intent == "appointment_booking" and entities.get("date"):
                return self.set_state(phone_number, ConversationState.COMPLETED, intent, entities)

        elif current_state == ConversationState.AWAITING_PAYMENT.value:
            if intent in ["payment_request", "payment_confirmed"]:
                return self.set_state(phone_number, ConversationState.PAID, intent, entities)
            elif intent == "cancel":
                return self.set_state(phone_number, ConversationState.CANCELLED, intent, entities)

        elif current_state in [ConversationState.PAID.value, ConversationState.COMPLETED.value]:
            return self.set_state(phone_number, ConversationState.BROWSING, intent, entities)

        return current

    def get_state_prompt(self, phone_number: str) -> str:
        data = self.get_state(phone_number)
        descriptions = {
            "browsing": "Customer is exploring options. Be helpful and ask what they need.",
            "inquiring": "Customer is interested in a service. Gather more details (date, time, quantity).",
            "confirming": "Customer provided details. Confirm before proceeding.",
            "awaiting_payment": "Customer needs to pay. Send payment link and wait.",
            "paid": "Payment received. Confirm and provide next steps.",
            "completed": "Order/appointment completed. Ask if they need anything else.",
            "human_takeover": "A human agent is handling this conversation. Do not respond.",
            "cancelled": "Customer cancelled. Ask if they want to start over.",
            "reset": "Conversation reset to browsing state."
        }
        return descriptions.get(data.get("state", "browsing"), "")

    def is_human_takeover(self, phone_number: str) -> bool:
        state = self.get_state(phone_number)
        return state.get("state") == ConversationState.HUMAN_TAKEOVER.value

    def reset(self, phone_number: str):
        if self._available:
            try:
                self.redis.delete(self._get_key(phone_number))
            except Exception:
                self._available = False


# ---------------------------------------------------------------------------
# Database State Machine (1.1 persistent memory, 1.5 multi-tenant isolation)
# ---------------------------------------------------------------------------

class DBStateMachine:
    """Database-backed state machine with per-tenant isolation and TTL auto-reset."""

    def __init__(self, ttl_hours: int = 48):
        self._available = True
        self.ttl_hours = ttl_hours

    async def _get_session(self, client_id: int, phone_number: str):
        from db import get_or_create_session
        async for session in get_session():
            return await get_or_create_session(session, client_id, phone_number, ttl_hours=self.ttl_hours)

    async def get_state(self, client_id: int, phone_number: str) -> Dict[str, Any]:
        try:
            conv_session = await self._get_session(client_id, phone_number)
            return {
                "state": conv_session.session_state or "browsing",
                "intent": conv_session.intent or "",
                "entities": conv_session.entities or {},
                "context": conv_session.context or {},
                "slot_data": conv_session.slot_data or {},
                "last_user_message": conv_session.last_user_message or "",
                "last_bot_message": conv_session.last_bot_message or "",
                "message_count": conv_session.message_count or 0,
                "is_human_takeover": conv_session.is_human_takeover or False,
                "updated_at": conv_session.updated_at.isoformat() if conv_session.updated_at else "",
            }
        except Exception:
            return {"state": "browsing", "intent": "", "entities": {}, "context": {}, "slot_data": {}, "is_human_takeover": False}

    async def set_state(self, client_id: int, phone_number: str, state, intent=None, entities=None, context=None, slot_data=None) -> Dict[str, Any]:
        try:
            conv_session = await self._get_session(client_id, phone_number)
            conv_session.session_state = state.value if hasattr(state, 'value') else state
            if intent is not None:
                conv_session.intent = intent
            if entities is not None:
                conv_session.entities = entities
            if context is not None:
                conv_session.context = context
            if slot_data is not None:
                conv_session.slot_data = slot_data
            conv_session.updated_at = datetime.now(timezone.utc)
            from db import async_session
            async with async_session() as session:
                await session.merge(conv_session)
                await session.commit()
                await session.refresh(conv_session)
            return await self.get_state(client_id, phone_number)
        except Exception:
            return {"state": "browsing", "intent": "", "entities": {}, "context": {}, "slot_data": {}, "is_human_takeover": False}

    async def transition(self, client_id: int, phone_number: str, intent: str, entities: Dict) -> Dict[str, Any]:
        current = await self.get_state(client_id, phone_number)
        current_state = current["state"]

        if intent == "human_handoff":
            return await self.set_state(client_id, phone_number, ConversationState.HUMAN_TAKEOVER, intent, entities)

        if current_state == ConversationState.BROWSING.value:
            if intent in ["appointment_booking", "order_placement", "pricing_query"]:
                return await self.set_state(client_id, phone_number, ConversationState.INQUIRING, intent, entities)

        elif current_state == ConversationState.INQUIRING.value:
            if intent == "appointment_booking" and entities.get("date"):
                return await self.set_state(client_id, phone_number, ConversationState.CONFIRMING, intent, entities)
            elif intent == "order_placement" and entities.get("product_name"):
                return await self.set_state(client_id, phone_number, ConversationState.CONFIRMING, intent, entities)
            elif intent == "payment_request":
                return await self.set_state(client_id, phone_number, ConversationState.AWAITING_PAYMENT, intent, entities)

        elif current_state == ConversationState.CONFIRMING.value:
            if intent == "payment_request":
                return await self.set_state(client_id, phone_number, ConversationState.AWAITING_PAYMENT, intent, entities)
            elif intent == "appointment_booking" and entities.get("date"):
                return await self.set_state(client_id, phone_number, ConversationState.COMPLETED, intent, entities)

        elif current_state == ConversationState.AWAITING_PAYMENT.value:
            if intent in ["payment_request", "payment_confirmed"]:
                return await self.set_state(client_id, phone_number, ConversationState.PAID, intent, entities)
            elif intent == "cancel":
                return await self.set_state(client_id, phone_number, ConversationState.CANCELLED, intent, entities)

        elif current_state in [ConversationState.PAID.value, ConversationState.COMPLETED.value]:
            return await self.set_state(client_id, phone_number, ConversationState.BROWSING, intent, entities)

        return current

    async def get_state_prompt(self, client_id: int, phone_number: str) -> str:
        data = await self.get_state(client_id, phone_number)
        descriptions = {
            "browsing": "Customer is exploring options. Be helpful and ask what they need.",
            "inquiring": "Customer is interested in a service. Gather more details (date, time, quantity).",
            "confirming": "Customer provided details. Confirm before proceeding.",
            "awaiting_payment": "Customer needs to pay. Send payment link and wait.",
            "paid": "Payment received. Confirm and provide next steps.",
            "completed": "Order/appointment completed. Ask if they need anything else.",
            "human_takeover": "A human agent is handling this conversation. Do not respond.",
            "cancelled": "Customer cancelled. Ask if they want to start over.",
            "reset": "Conversation reset to browsing state."
        }
        return descriptions.get(data.get("state", "browsing"), "")

    async def is_human_takeover(self, client_id: int, phone_number: str) -> bool:
        state = await self.get_state(client_id, phone_number)
        return state.get("is_human_takeover", False) or state.get("state") == ConversationState.HUMAN_TAKEOVER.value

    async def reset(self, client_id: int, phone_number: str):
        try:
            from db import async_session
            async with async_session() as session:
                result = await session.execute(
                    select(ConversationSession).where(
                        ConversationSession.client_id == client_id,
                        ConversationSession.phone_number == phone_number,
                    )
                )
                rows = result.scalars().all()
                for row in rows:
                    row.session_state = "browsing"
                    row.intent = None
                    row.entities = {}
                    row.slot_data = {}
                    row.context = {}
                    row.last_user_message = None
                    row.last_bot_message = None
                    row.message_count = 0
                    row.is_human_takeover = False
                    row.updated_at = datetime.now(timezone.utc)
                    await session.merge(row)
                await session.commit()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Global state machine instance
# ---------------------------------------------------------------------------

state_machine = None

def get_state_machine():
    """Get the global state machine instance, initializing if needed."""
    global state_machine
    if state_machine is None:
        try:
            sm = RedisStateMachine()
            if sm._available:
                state_machine = sm
            else:
                state_machine = DBStateMachine()
        except Exception:
            state_machine = DBStateMachine()
    return state_machine

def set_state_machine(sm):
    """Set the global state machine instance."""
    global state_machine
    state_machine = sm