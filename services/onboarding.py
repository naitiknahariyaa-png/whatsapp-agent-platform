"""
Owner Onboarding Wizard — Multi-step business provisioning.
Every owner who signs up feeds the Manager Agent + worker system the data it needs.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from db import (
    async_session,
    Owner,
    Client,
    CatalogItem,
    Policy,
    OwnerApiKey,
)
from secrets_manager import secrets

logger = logging.getLogger("onboarding")

# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass
class OnboardingStep:
    step_id: str
    title: str
    description: str
    fields: List[str]

@dataclass
class OnboardingState:
    owner_id: Optional[int] = None
    client_id: Optional[int] = None
    current_step: int = 0
    data: Dict[str, Any] = field(default_factory=dict)
    is_complete: bool = False
    test_conversation_passed: bool = False


# ---------------------------------------------------------------------------
# Wizard definition
# ---------------------------------------------------------------------------

WIZARD_STEPS = [
    OnboardingStep(
        step_id="identity",
        title="Business Identity",
        description="Tell us about your business",
        fields=["business_name", "owner_name", "owner_phone", "owner_email", "business_category"],
    ),
    OnboardingStep(
        step_id="api_keys",
        title="Connect APIs",
        description="Connect WhatsApp and payment gateways",
        fields=["whatsapp_phone", "whatsapp_api_key", "payment_provider", "payment_api_key", "payment_secret"],
    ),
    OnboardingStep(
        step_id="profile",
        title="Business Profile",
        description="Set your hours, timezone, and brand voice",
        fields=["address", "business_hours", "timezone", "languages", "brand_voice", "currency"],
    ),
    OnboardingStep(
        step_id="catalog",
        title="Catalog / Menu",
        description="Add your products or services",
        fields=["catalog_items"],
    ),
    OnboardingStep(
        step_id="policies",
        title="Policies & Escalation",
        description="Set rules and escalation preferences",
        fields=["refund_policy", "cancellation_policy", "delivery_radius_km", "min_order_amount",
                "escalation_contact", "escalation_channel", "quiet_hours_start", "quiet_hours_end"],
    ),
    OnboardingStep(
        step_id="knowledge",
        title="Knowledge Base (optional)",
        description="Upload docs for smarter FAQ answering",
        fields=["knowledge_docs"],
    ),
    OnboardingStep(
        step_id="test",
        title="Test Conversation",
        description="Try a sample conversation with your AI",
        fields=["test_passed"],
    ),
]

# ---------------------------------------------------------------------------
# Core onboarding functions
# ---------------------------------------------------------------------------

async def create_owner(data: Dict[str, Any]) -> Owner:
    """
    Create a new owner and linked client.
    Returns the Owner row.
    """
    async with async_session() as session:
        # Create client first
        client = Client(
            business_name=data.get("business_name", "My Business"),
            vertical="general",
            whatsapp_number=data.get("whatsapp_phone", ""),
            plan="trial",
            is_active=True,
        )
        session.add(client)
        await session.flush()

        # Hash password if provided
        password_hash = None
        if data.get("password"):
            from auth import hash_password
            password_hash = hash_password(data["password"])

        # Create owner
        owner = Owner(
            client_id=client.id,
            business_name=data.get("business_name", ""),
            owner_name=data.get("owner_name", ""),
            owner_phone=data.get("owner_phone", ""),
            owner_email=data.get("owner_email"),
            password_hash=password_hash,
            business_category=data.get("business_category", "general"),
            address=data.get("address"),
            business_hours=data.get("business_hours"),
            timezone=data.get("timezone", "Asia/Kolkata"),
            languages=data.get("languages", ["en"]),
            brand_voice=data.get("brand_voice", "casual"),
            currency=data.get("currency", "INR"),
            escalation_contact=data.get("escalation_contact"),
            escalation_channel=data.get("escalation_channel", "whatsapp"),
            quiet_hours_start=data.get("quiet_hours_start"),
            quiet_hours_end=data.get("quiet_hours_end"),
        )
        session.add(owner)
        await session.flush()

        # Create default policy
        policy = Policy(
            owner_id=owner.id,
            refund_policy=data.get("refund_policy"),
            cancellation_policy=data.get("cancellation_policy"),
            delivery_radius_km=data.get("delivery_radius_km"),
            min_order_amount=data.get("min_order_amount"),
            discount_rules=data.get("discount_rules", {}),
            quiet_hours=data.get("quiet_hours", {}),
        )
        session.add(policy)

        # Store API keys encrypted
        if data.get("whatsapp_api_key"):
            _store_api_key(session, owner.id, "whatsapp_business",
                           data.get("whatsapp_phone", ""),
                           data["whatsapp_api_key"], data.get("whatsapp_api_secret", ""))
        if data.get("payment_provider") and data.get("payment_api_key"):
            _store_api_key(session, owner.id, data["payment_provider"],
                           data.get("payment_key_id", ""),
                           data["payment_api_key"], data.get("payment_secret", ""))

        await session.commit()
        await session.refresh(owner)
        return owner


def _store_api_key(session, owner_id: int, provider: str, key_id: str, api_key: str, api_secret: str):
    """Store an API key encrypted."""
    encrypted_key = secrets.encrypt(api_key) if api_key else None
    encrypted_secret = secrets.encrypt(api_secret) if api_secret else None
    key_mask = f"****{api_key[-4:]}" if api_key and len(api_key) >= 4 else "****"

    key_row = OwnerApiKey(
        owner_id=owner_id,
        provider=provider,
        key_id=key_id,
        encrypted_key=encrypted_key,
        encrypted_secret=encrypted_secret,
        key_mask=key_mask,
    )
    session.add(key_row)


async def add_catalog_items(owner_id: int, items: List[Dict[str, Any]]) -> List[CatalogItem]:
    """Add catalog items for an owner."""
    created = []
    async with async_session() as session:
        for item_data in items:
            item = CatalogItem(
                owner_id=owner_id,
                name=item_data.get("name", ""),
                description=item_data.get("description"),
                price=float(item_data.get("price", 0)),
                currency=item_data.get("currency", "INR"),
                prep_time_minutes=int(item_data.get("prep_time_minutes", 15)),
                prep_time_tier=item_data.get("prep_time_tier", "normal"),
                category=item_data.get("category"),
                tags=item_data.get("tags", []),
                available=item_data.get("available", True),
                popularity_score=item_data.get("popularity_score", 0),
                margin=item_data.get("margin", 0.0),
                priority=item_data.get("priority", 0),
            )
            session.add(item)
            created.append(item)
        await session.commit()
        for item in created:
            await session.refresh(item)
    return created


async def get_owner_catalog(owner_id: int) -> List[Dict[str, Any]]:
    """Get all catalog items for an owner."""
    async with async_session() as session:
        result = await session.execute(
            select(CatalogItem).where(CatalogItem.owner_id == owner_id, CatalogItem.available)
            .order_by(CatalogItem.priority.desc(), CatalogItem.popularity_score.desc())
        )
        items = result.scalars().all()
        return [item.to_dict() for item in items]


async def get_owner_policy(owner_id: int) -> Optional[Policy]:
    """Get policy for an owner."""
    async with async_session() as session:
        result = await session.execute(select(Policy).where(Policy.owner_id == owner_id))
        return result.scalar_one_or_none()


async def get_owner_by_phone(phone: str) -> Optional[Owner]:
    """Look up owner by phone number."""
    async with async_session() as session:
        result = await session.execute(
            select(Owner).where(Owner.owner_phone == phone)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Test conversation simulator
# ---------------------------------------------------------------------------

async def run_test_conversation(owner_id: int, test_message: str) -> Dict[str, Any]:
    """
    Run a simulated customer message through the constraint engine
    using the owner's actual catalog. Returns the AI's proposed reply
    and whether it looks correct.
    """
    from services.constraint_reply_engine import generate_constraint_reply

    reply = await generate_constraint_reply(
        owner_id=owner_id,
        message=test_message,
        language="auto",
    )

    return {
        "test_message": test_message,
        "ai_reply": reply,
        "passed": bool(reply and "sorry" not in reply.lower()[:20]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Onboarding flow controller
# ---------------------------------------------------------------------------

class OnboardingWizard:
    """
    Stateful multi-step wizard.
    Call advance() with step data; call complete() to finish.
    """

    def __init__(self):
        self._states: Dict[str, OnboardingState] = {}

    def get_or_create_state(self, session_id: str) -> OnboardingState:
        if session_id not in self._states:
            self._states[session_id] = OnboardingState()
        return self._states[session_id]

    def get_step(self, index: int) -> Optional[OnboardingStep]:
        if 0 <= index < len(WIZARD_STEPS):
            return WIZARD_STEPS[index]
        return None

    def current_step(self, state: OnboardingState) -> Optional[OnboardingStep]:
        return self.get_step(state.current_step)

    async def advance(self, state: OnboardingState, step_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Advance the wizard by one step. Returns the next step or completion result.
        """
        step = self.current_step(state)
        if not step:
            return {"status": "complete", "state": state}

        # Merge step data
        state.data.update(step_data)

        # If this is the identity step, create the owner
        if step.step_id == "identity":
            try:
                owner = await create_owner(state.data)
                state.owner_id = owner.id
                state.client_id = owner.client_id
                state.data["owner_id"] = owner.id
                state.data["client_id"] = owner.client_id
            except Exception as e:
                logger.error(f"Owner creation failed: {e}")
                return {"status": "error", "error": str(e), "state": state}

        # If this is the catalog step, add items
        if step.step_id == "catalog" and state.owner_id:
            items = step_data.get("catalog_items", [])
            if items:
                await add_catalog_items(state.owner_id, items)
                state.data["catalog_items"] = items

        # Move to next step
        state.current_step += 1

        # Check if complete
        if state.current_step >= len(WIZARD_STEPS):
            state.is_complete = True
            return {"status": "complete", "state": state}

        next_step = self.get_step(state.current_step)
        return {
            "status": "next",
            "state": state,
            "next_step": {
                "step_id": next_step.step_id,
                "title": next_step.title,
                "description": next_step.description,
                "fields": next_step.fields,
            } if next_step else None,
        }

    async def complete(self, state: OnboardingState) -> Dict[str, Any]:
        """Finalize onboarding — mark owner as onboarded."""
        if not state.owner_id:
            return {"status": "error", "error": "No owner created"}

        async with async_session() as session:
            result = await session.execute(select(Owner).where(Owner.id == state.owner_id))
            owner = result.scalar_one_or_none()
            if owner:
                owner.onboarded_at = datetime.now(timezone.utc)
                owner.is_active = True
                await session.commit()

        state.is_complete = True
        return {
            "status": "complete",
            "owner_id": state.owner_id,
            "client_id": state.client_id,
            "message": "Onboarding complete! Your AI assistant is now live.",
        }

    async def run_test(self, state: OnboardingState, test_message: str) -> Dict[str, Any]:
        """Run the test conversation simulation."""
        if not state.owner_id:
            return {"status": "error", "error": "Complete identity step first"}

        result = await run_test_conversation(state.owner_id, test_message)
        state.test_conversation_passed = result.get("passed", False)
        state.data["test_result"] = result
        return result


# Module-level singleton
_wizard = OnboardingWizard()


def get_wizard() -> OnboardingWizard:
    return _wizard
