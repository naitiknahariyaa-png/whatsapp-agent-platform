"""
Prompt Versioning System
========================

Stores agent system prompts in DB with version numbers, not hardcoded strings.
Enables:
- Instant rollback of bad prompt changes
- A/B testing of prompt variants
- Audit trail of prompt changes
- Per-vertical, per-task prompt management
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

logger = logging.getLogger("prompt_versioning")

try:
    from db import async_session, Base
    from sqlalchemy import select, Column, String, Text, Integer, DateTime, JSON, ForeignKey
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.dialects.postgresql import UUID
    import uuid
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    logger.warning("DB not available for prompt versioning")


class PromptType(Enum):
    """Types of prompts that can be versioned."""
    SYSTEM = "system"                    # Main system prompt
    INTENT_CLASSIFICATION = "intent_classification"
    ENTITY_EXTRACTION = "entity_extraction"
    RESPONSE_GENERATION = "response_generation"
    PLANNING = "planning"                # ManagerAgent planning
    VERIFICATION = "verification"        # Tool result verification
    SUMMARIZATION = "summarization"      # Conversation summarization
    VERTICAL_CONTEXT = "vertical_context"  # Vertical-specific context
    SKILL = "skill"                      # Skill-specific prompts
    GUARDRAIL = "guardrail"              # Guardrail classifier prompts


@dataclass
class PromptVersion:
    """A single version of a prompt."""
    id: str
    prompt_type: PromptType
    vertical: str = "general"
    version: int = 1
    content: str = ""
    variables: Dict[str, str] = field(default_factory=dict)  # {{variable}} -> description
    description: str = ""
    is_active: bool = True
    created_by: str = "system"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    parent_version: Optional[str] = None  # For branching

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["prompt_type"] = self.prompt_type.value
        return d


if DB_AVAILABLE:
    class PromptVersionDB(Base):
        __tablename__ = "prompt_versions"
        id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
        prompt_type: Mapped[str] = mapped_column(String(50), index=True)
        vertical: Mapped[str] = mapped_column(String(50), index=True, default="general")
        version: Mapped[int] = mapped_column(Integer, default=1)
        content: Mapped[str] = mapped_column(Text)
        variables: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
        description: Mapped[str] = mapped_column(Text, default="")
        is_active: Mapped[bool] = mapped_column(default=True)
        created_by: Mapped[str] = mapped_column(String(100), default="system")
        created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
        parent_version: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

        __table_args__ = (
            # Unique constraint: one active version per (type, vertical, version)
        )


class PromptRegistry:
    """
    Manages prompt versions with full versioning, rollback, and A/B testing support.
    """

    def __init__(self):
        self._cache: Dict[str, PromptVersion] = {}
        self._ab_assignments: Dict[str, str] = {}  # conversation_id -> version_id

    # ─── CRUD ────────────────────────────────────────────────────────

    async def create(self, prompt: PromptVersion) -> PromptVersion:
        """Create a new prompt version."""
        if not DB_AVAILABLE:
            self._cache[prompt.id] = prompt
            return prompt

        async with async_session() as session:
            db_prompt = PromptVersionDB(
                id=prompt.id,
                prompt_type=prompt.prompt_type.value,
                vertical=prompt.vertical,
                version=prompt.version,
                content=prompt.content,
                variables=prompt.variables,
                description=prompt.description,
                is_active=prompt.is_active,
                created_by=prompt.created_by,
                parent_version=prompt.parent_version,
            )
            session.add(db_prompt)
            await session.commit()
            await session.refresh(db_prompt)
            self._cache[prompt.id] = prompt
            logger.info("Created prompt %s v%d (%s)", prompt.prompt_type.value, prompt.version, prompt.id)
            return prompt

    async def get(self, prompt_id: str) -> Optional[PromptVersion]:
        """Get a specific prompt version by ID."""
        if prompt_id in self._cache:
            return self._cache[prompt_id]

        if not DB_AVAILABLE:
            return None

        async with async_session() as session:
            result = await session.execute(
                select(PromptVersionDB).where(PromptVersionDB.id == prompt_id)
            )
            db_prompt = result.scalar_one_or_none()
            if db_prompt:
                prompt = self._db_to_prompt(db_prompt)
                self._cache[prompt.id] = prompt
                return prompt
        return None

    async def get_active(self, prompt_type: PromptType, vertical: str = "general") -> Optional[PromptVersion]:
        """Get the currently active version for a prompt type + vertical."""
        cache_key = f"{prompt_type.value}:{vertical}:active"
        if cache_key in self._cache:
            return self._cache[cache_key]

        if not DB_AVAILABLE:
            return None

        async with async_session() as session:
            result = await session.execute(
                select(PromptVersionDB).where(
                    PromptVersionDB.prompt_type == prompt_type.value,
                    PromptVersionDB.vertical == vertical,
                    PromptVersionDB.is_active == True,
                ).order_by(PromptVersionDB.version.desc()).limit(1)
            )
            db_prompt = result.scalar_one_or_none()
            if db_prompt:
                prompt = self._db_to_prompt(db_prompt)
                self._cache[cache_key] = prompt
                return prompt
        return None

    async def list_versions(self, prompt_type: PromptType, vertical: str = "general") -> List[PromptVersion]:
        """List all versions for a prompt type + vertical."""
        if not DB_AVAILABLE:
            return []

        async with async_session() as session:
            result = await session.execute(
                select(PromptVersionDB).where(
                    PromptVersionDB.prompt_type == prompt_type.value,
                    PromptVersionDB.vertical == vertical,
                ).order_by(PromptVersionDB.version.desc())
            )
            return [self._db_to_prompt(p) for p in result.scalars().all()]

    async def set_active(self, prompt_id: str, active: bool = True) -> bool:
        """Activate/deactivate a prompt version (only one active per type+vertical)."""
        if not DB_AVAILABLE:
            return False

        async with async_session() as session:
            # First, deactivate all others of same type+vertical
            prompt = await self.get(prompt_id)
            if not prompt:
                return False

            await session.execute(
                PromptVersionDB.__table__.update()
                .where(
                    PromptVersionDB.prompt_type == prompt.prompt_type.value,
                    PromptVersionDB.vertical == prompt.vertical,
                )
                .values(is_active=False)
            )

            # Activate this one
            await session.execute(
                PromptVersionDB.__table__.update()
                .where(PromptVersionDB.id == prompt_id)
                .values(is_active=active)
            )
            await session.commit()

            # Invalidate cache
            cache_key = f"{prompt.prompt_type.value}:{prompt.vertical}:active"
            self._cache.pop(cache_key, None)
            return True

    async def create_new_version(self, base_id: str, new_content: str,
                                  description: str = "", created_by: str = "system") -> PromptVersion:
        """Create a new version based on an existing prompt."""
        base = await self.get(base_id)
        if not base:
            raise ValueError(f"Base prompt {base_id} not found")

        new_version = PromptVersion(
            id=str(uuid.uuid4()),
            prompt_type=base.prompt_type,
            vertical=base.vertical,
            version=base.version + 1,
            content=new_content,
            variables=base.variables.copy(),
            description=description or f"Version {base.version + 1} based on {base_id}",
            created_by=created_by,
            parent_version=base_id,
        )
        return await self.create(new_version)

    # ─── A/B Testing ────────────────────────────────────────────────

    async def assign_ab_test(self, conversation_id: str, variant_ids: List[str], weights: Optional[List[float]] = None) -> str:
        """Assign a conversation to an A/B test variant."""
        if not weights:
            weights = [1.0 / len(variant_ids)] * len(variant_ids)

        import random
        chosen = random.choices(variant_ids, weights=weights)[0]
        self._ab_assignments[conversation_id] = chosen
        return chosen

    def get_ab_assignment(self, conversation_id: str) -> Optional[str]:
        return self._ab_assignments.get(conversation_id)

    # ─── Rollback ──────────────────────────────────────────────────

    async def rollback(self, prompt_type: PromptType, vertical: str = "general", target_version: int = None) -> bool:
        """Rollback to a previous version."""
        versions = await self.list_versions(prompt_type, vertical)
        if not versions:
            return False

        if target_version is None:
            # Rollback to previous version (second highest)
            if len(versions) < 2:
                return False
            target = versions[1]
        else:
            target = next((v for v in versions if v.version == target_version), None)
            if not target:
                return False

        return await self.set_active(target.id, True)

    # ─── Helpers ───────────────────────────────────────────────────

    def _db_to_prompt(self, db: "PromptVersionDB") -> PromptVersion:
        return PromptVersion(
            id=db.id,
            prompt_type=PromptType(db.prompt_type),
            vertical=db.vertical,
            version=db.version,
            content=db.content,
            variables=db.variables or {},
            description=db.description,
            is_active=db.is_active,
            created_by=db.created_by,
            created_at=db.created_at.isoformat() if db.created_at else "",
            parent_version=db.parent_version,
        )


# ─── Built-in Default Prompts ──────────────────────────────────────

DEFAULT_PROMPTS = {
    PromptType.SYSTEM: {
        "general": """You are a helpful WhatsApp AI assistant for Indian businesses.
Respond in Hinglish (Hindi + English mix) - casual, friendly, and professional.
Keep responses concise (2-3 lines max). Use emojis appropriately.""",
        "doctor": """You are a medical clinic assistant. Help with appointments, symptoms, prescriptions, lab reports.
Always add disclaimer: 'I am an AI assistant, not a doctor. For emergencies, call 108.'
Respond in Hinglish. Keep responses concise.""",
        "lawyer": """You are a legal assistant. Help with case consultations, legal documents, appointments.
Always add disclaimer: 'I am an AI assistant, not a lawyer. For legal advice, consult a qualified attorney.'
Respond in Hinglish. Keep responses concise.""",
    },
    PromptType.INTENT_CLASSIFICATION: {
        "general": """You are an intent classifier for a WhatsApp AI assistant for Indian businesses.
Analyze the user message and classify into ONE intent: greeting, farewell, appointment_booking, pricing_query, support, lead_enquiry, document_request, symptom_check, prescription_request, lab_report, case_inquiry, itr_inquiry, menu_inquiry, order_placement, payment_request, human_handoff, general_query.
Extract entities: date, time, person_name, location, product_name, quantity, phone_number.
Return ONLY valid JSON.""",
    },
    PromptType.RESPONSE_GENERATION: {
        "general": """You are a helpful WhatsApp AI assistant for a {vertical} business.
Respond in Hinglish (Hindi + English mix) - casual, friendly, professional.
Keep responses concise (2-3 lines max). Use emojis appropriately.
If user needs more info (date, time, name), ask for it.""",
    },
    PromptType.PLANNING: {
        "general": """You are the CEO Manager. Your sole responsibility is orchestration.
PLANNING FORMAT: JSON list: [ {"agent": "AgentName", "task": "..."} ]
RULES: 1. NEVER answer domain questions yourself. Delegate to specialists.
2. Specialists: SalesAgent, SupportAgent, ConciergeAgent.
3. Verify every specialist result against original intent before accepting.""",
    },
    PromptType.VERIFICATION: {
        "general": """User Input: {original_input}\nTask: {task}\nResponse: {result}\n\nDoes the response accurately satisfy the task? Respond ONLY in JSON: {"valid": true/false, "feedback": "..."}""",
    },
    PromptType.SUMMARIZATION: {
        "general": """Summarize the conversation for a WhatsApp business assistant.
Return ONLY valid JSON: {"summary": "one-line summary", "needs": ["list"], "missing_info": ["list"]}""",
    },
}


# ─── Global Registry ───────────────────────────────────────────────

prompt_registry = PromptRegistry()

async def seed_default_prompts():
    """Seed the database with default prompts."""
    for ptype, verticals in DEFAULT_PROMPTS.items():
        for vertical, content in verticals.items():
            existing = await prompt_registry.get_active(ptype, vertical)
            if not existing:
                prompt = PromptVersion(
                    id=str(uuid.uuid4()),
                    prompt_type=ptype,
                    vertical=vertical,
                    version=1,
                    content=content,
                    description="Default seed prompt",
                    created_by="system",
                )
                await prompt_registry.create(prompt)
                logger.info("Seeded default prompt: %s/%s", ptype.value, vertical)