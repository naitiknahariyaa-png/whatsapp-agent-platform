"""
Redis-backed State Machine - persistent conversation state
"""
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
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
        self._available = False  # Matches RedisStateMachine interface

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
        current["updated_at"] = datetime.utcnow().isoformat()
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
            # Test connection
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
        current["updated_at"] = datetime.utcnow().isoformat()
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


# Global state machine instance
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
                state_machine = InMemoryStateMachine()
        except Exception:
            state_machine = InMemoryStateMachine()
    return state_machine

def set_state_machine(sm):
    """Set the global state machine instance."""
    global state_machine
    state_machine = sm