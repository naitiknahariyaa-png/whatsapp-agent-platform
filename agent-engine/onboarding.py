"""
Multi-Tenant Owner Onboarding — Section 2 of the WhatsApp Agent Company spec.

Exposes a FastAPI router at /api/onboarding/* that:
  1. Creates owners (the business entity that signs up)
  2. Stores their catalog (menu / services / SKUs)
  3. Stores their policies (refund, cancellation, autonomous-decision caps)
  4. Stores encrypted third-party API keys (WhatsApp, payments, etc.)
  5. Runs the ranking-aware catalog query that Section 3 will consult
  6. Finalizes onboarding (links Owner → Client, sets onboarded_at)

Tenant isolation: every read and write filters on owner_id. The
router is mounted without a global dependency so callers must always
pass owner_id explicitly; there is no "fetch the current owner" magic.

NOTE: Full auth (JWT/session) is intentionally NOT required at this
layer — the existing /api/auth/* routes handle that. This router
assumes the caller has already authenticated and passes owner_id in
the URL. The frontend wizard will gate this in step 1.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import (
    async_session,
    Owner,
    CatalogItem,
    Policy,
    OwnerApiKey,
    Client,
    hmac_phone_hash,
)
from crypto_fields import encrypt_value

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


# ─── DB session dependency (replaces get_session() for this router) ───

async def _get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


# ─── Schemas ──────────────────────────────────────────────────────────

VALID_CATEGORIES = {
    "restaurant", "clinic", "salon", "retail", "agency",
    "doctor", "lawyer", "ca", "mba", "general",
}
VALID_BRAND_VOICES = {"formal", "casual", "playful"}
VALID_PROVIDERS = {
    "whatsapp_business", "razorpay", "stripe",
    "google_calendar", "telegram", "openai", "groq", "other",
}
VALID_TIERS = {"fast", "normal", "slow"}
VALID_RELAXATION = {"prefer_speed", "prefer_budget", "strict"}


class OwnerCreate(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=255)
    owner_name: str = Field(..., min_length=1, max_length=255)
    owner_phone: str = Field(..., min_length=8, max_length=32)
    owner_email: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    business_category: str = Field("general")
    address: Optional[str] = None
    business_hours: Optional[str] = Field(None, max_length=255)
    timezone: str = Field("Asia/Kolkata", max_length=50)
    languages: List[str] = Field(default_factory=lambda: ["hi", "en"])
    brand_voice: str = Field("casual")
    currency: str = Field("INR", max_length=8)
    escalation_contact: Optional[str] = None
    escalation_channel: Optional[str] = None
    quiet_hours_start: Optional[str] = Field(None, max_length=8)
    quiet_hours_end: Optional[str] = Field(None, max_length=8)

    @field_validator("business_category")
    @classmethod
    def _v_cat(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            raise ValueError(f"business_category must be one of {sorted(VALID_CATEGORIES)}")
        return v

    @field_validator("brand_voice")
    @classmethod
    def _v_voice(cls, v: str) -> str:
        if v not in VALID_BRAND_VOICES:
            raise ValueError(f"brand_voice must be one of {sorted(VALID_BRAND_VOICES)}")
        return v


class OwnerOut(BaseModel):
    id: int
    business_name: str
    owner_name: str
    business_category: str
    timezone: str
    languages: List[str]
    brand_voice: str
    currency: str
    is_active: bool
    onboarded_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class CatalogItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    price: float = Field(0.0, ge=0)
    currency: str = Field("INR", max_length=8)
    prep_time_minutes: int = Field(15, ge=0, le=1440)
    prep_time_tier: str = Field("normal")
    category: Optional[str] = Field(None, max_length=100)
    tags: List[str] = Field(default_factory=list)
    available: bool = True
    popularity_score: int = Field(0, ge=0)
    margin: float = Field(0.0, ge=0.0, le=1.0)
    priority: int = Field(0, ge=0, le=1000)

    @field_validator("prep_time_tier")
    @classmethod
    def _v_tier(cls, v: str) -> str:
        if v not in VALID_TIERS:
            raise ValueError(f"prep_time_tier must be one of {sorted(VALID_TIERS)}")
        return v


class CatalogItemOut(BaseModel):
    id: int
    owner_id: int
    name: str
    description: Optional[str]
    price: float
    currency: str
    prep_time_minutes: int
    prep_time_tier: str
    category: Optional[str]
    tags: List[str]
    available: bool
    popularity_score: int
    margin: float
    priority: int

    class Config:
        from_attributes = True


class CatalogBulkCreate(BaseModel):
    items: List[CatalogItemCreate]


class PolicyCreate(BaseModel):
    refund_policy: Optional[str] = None
    cancellation_policy: Optional[str] = None
    delivery_radius_km: Optional[float] = Field(None, ge=0)
    min_order_amount: Optional[float] = Field(None, ge=0)
    discount_rules: dict = Field(default_factory=dict)
    quiet_hours: dict = Field(default_factory=dict)
    relaxation_policy: str = Field("prefer_speed")
    fastest_guarantee_minutes: int = Field(15, ge=0, le=1440)
    max_autonomous_discount_pct: float = Field(5.0, ge=0.0, le=100.0)
    max_autonomous_substitution: bool = True
    escalation_triggers: dict = Field(default_factory=dict)

    @field_validator("relaxation_policy")
    @classmethod
    def _v_relax(cls, v: str) -> str:
        if v not in VALID_RELAXATION:
            raise ValueError(f"relaxation_policy must be one of {sorted(VALID_RELAXATION)}")
        return v


class PolicyOut(BaseModel):
    id: int
    owner_id: int
    refund_policy: Optional[str]
    cancellation_policy: Optional[str]
    delivery_radius_km: Optional[float]
    min_order_amount: Optional[float]
    discount_rules: dict
    quiet_hours: dict
    relaxation_policy: str
    fastest_guarantee_minutes: int
    max_autonomous_discount_pct: float
    max_autonomous_substitution: bool
    escalation_triggers: dict

    class Config:
        from_attributes = True


class ApiKeyCreate(BaseModel):
    provider: str
    key_id: Optional[str] = None
    key: Optional[str] = None
    secret: Optional[str] = None

    @field_validator("provider")
    @classmethod
    def _v_provider(cls, v: str) -> str:
        if v not in VALID_PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(VALID_PROVIDERS)}")
        return v


class ApiKeyOut(BaseModel):
    """Returned to the owner — NEVER includes the plaintext key/secret."""
    id: int
    owner_id: int
    provider: str
    key_id: Optional[str]
    key_mask: str
    last_used_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class WizardState(BaseModel):
    owner: Optional[OwnerOut] = None
    catalog: List[CatalogItemOut] = Field(default_factory=list)
    policy: Optional[PolicyOut] = None
    keys: List[ApiKeyOut] = Field(default_factory=list)
    catalog_count: int = 0


# ─── Helpers ──────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    """Lightweight password hashing using PBKDF2 (no extra dep needed).
    Replace with passlib.bcrypt in production if desired."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), salt, 100_000)
    return f"pbkdf2_sha256$100000${salt.hex()}${dk.hex()}"


def _mask_key(plaintext: str) -> str:
    """Return a safe-to-display fingerprint: last 4 chars masked with ****."""
    if not plaintext:
        return "****"
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"****{tail}"


async def _get_owner_or_404(db: AsyncSession, owner_id: int) -> Owner:
    result = await db.execute(select(Owner).where(Owner.id == owner_id))
    owner = result.scalar_one_or_none()
    if not owner:
        raise HTTPException(404, f"owner {owner_id} not found")
    return owner


# ─── Routes: Owners ───────────────────────────────────────────────────

@router.post("/owners", response_model=OwnerOut, status_code=201)
async def create_owner(payload: OwnerCreate, db: AsyncSession = Depends(_get_db)) -> Owner:
    # Ensure phone hash index works for lookups
    phone_h = hmac_phone_hash(payload.owner_phone)
    existing = await db.execute(
        select(Owner).where(Owner.owner_phone_hash == phone_h)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "owner with this phone already exists")

    data = payload.model_dump(exclude={"password"})
    if payload.password:
        data["password_hash"] = _hash_password(payload.password)

    owner = Owner(**data, owner_phone_hash=phone_h)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    return owner


@router.get("/owners/{owner_id}", response_model=WizardState)
async def get_owner_wizard_state(
    owner_id: int, db: AsyncSession = Depends(_get_db)
) -> WizardState:
    """Return everything the onboarding wizard needs in one call."""
    owner = await _get_owner_or_404(db, owner_id)
    cat_res = await db.execute(
        select(CatalogItem).where(CatalogItem.owner_id == owner_id)
    )
    catalog = cat_res.scalars().all()
    pol_res = await db.execute(select(Policy).where(Policy.owner_id == owner_id))
    policy = pol_res.scalar_one_or_none()
    keys_res = await db.execute(
        select(OwnerApiKey).where(OwnerApiKey.owner_id == owner_id)
    )
    keys = keys_res.scalars().all()
    return WizardState(
        owner=OwnerOut.model_validate(owner),
        catalog=[CatalogItemOut.model_validate(c) for c in catalog],
        policy=PolicyOut.model_validate(policy) if policy else None,
        keys=[ApiKeyOut.model_validate(k) for k in keys],
        catalog_count=len(catalog),
    )


@router.post("/owners/{owner_id}/onboard/complete", response_model=OwnerOut)
async def complete_onboarding(
    owner_id: int, db: AsyncSession = Depends(_get_db)
) -> Owner:
    """Mark the owner as fully onboarded, link to a Client if needed."""
    owner = await _get_owner_or_404(db, owner_id)
    if owner.onboarded_at:
        return owner  # idempotent
    if not owner.client_id:
        # Auto-create a Client row so the existing message-routing works.
        # Use a unique placeholder WhatsApp number — owner can update later.
        placeholder = f"pending_{owner_id}_{secrets.token_hex(4)}"
        client = Client(
            business_name=owner.business_name,
            vertical=owner.business_category,
            whatsapp_number=placeholder,
            plan="trial",
        )
        db.add(client)
        await db.flush()
        owner.client_id = client.id
    owner.onboarded_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(owner)
    return owner


# ─── Routes: Catalog ──────────────────────────────────────────────────

@router.post(
    "/owners/{owner_id}/catalog",
    response_model=CatalogItemOut,
    status_code=201,
)
async def add_catalog_item(
    owner_id: int,
    payload: CatalogItemCreate,
    db: AsyncSession = Depends(_get_db),
) -> CatalogItem:
    await _get_owner_or_404(db, owner_id)
    item = CatalogItem(owner_id=owner_id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.post(
    "/owners/{owner_id}/catalog/bulk",
    response_model=List[CatalogItemOut],
    status_code=201,
)
async def add_catalog_items_bulk(
    owner_id: int,
    payload: CatalogBulkCreate,
    db: AsyncSession = Depends(_get_db),
) -> List[CatalogItem]:
    await _get_owner_or_404(db, owner_id)
    items = [
        CatalogItem(owner_id=owner_id, **i.model_dump()) for i in payload.items
    ]
    db.add_all(items)
    await db.commit()
    for it in items:
        await db.refresh(it)
    return items


@router.get(
    "/owners/{owner_id}/catalog",
    response_model=List[CatalogItemOut],
)
async def list_catalog(
    owner_id: int,
    available_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    db: AsyncSession = Depends(_get_db),
) -> List[CatalogItem]:
    """List catalog items with optional pagination.
    `skip` offsets the result set, `limit` caps the number of items returned.
    """
    await _get_owner_or_404(db, owner_id)
    stmt = select(CatalogItem).where(CatalogItem.owner_id == owner_id)
    if available_only:
        stmt = stmt.where(CatalogItem.available.is_(True))
    stmt = stmt.order_by(CatalogItem.priority.desc(), CatalogItem.name.asc()).offset(skip).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


# ─── Routes: Catalog ranking (Section 3 input) ───────────────────────

@router.get("/owners/{owner_id}/catalog/rank", response_model=List[CatalogItemOut])
async def rank_catalog(
    owner_id: int,
    budget_max: Optional[float] = Query(None, ge=0, description="Max price the customer can pay"),
    prep_time_max_minutes: Optional[int] = Query(None, ge=0, le=1440),
    tier: Optional[str] = Query(None, description="fast / normal / slow — or 'fast' for jaldi-chahiye style"),
    category: Optional[str] = Query(None, max_length=100),
    tag: Optional[str] = Query(None, description="Single tag to filter by (e.g. 'veg')"),
    require_all_tags: bool = Query(False, description="If true, item must have ALL given tags"),
    tags: Optional[str] = Query(None, description="Comma-separated list of tags to filter by"),
    relax: bool = Query(False, description="If true and no items match, relax the looser constraint first"),
    db: AsyncSession = Depends(_get_db),
) -> List[CatalogItem]:
    """Constraint-aware ranking (Section 3.3 of the spec).

    Filters owner_id = X first (mandatory), then budget, prep time, tier,
    category, and tags. Sorts by a composite score:
        priority DESC, popularity_score DESC, margin DESC, prep_time ASC
    so the first result is what the AI should mention first.

    If `relax=true` and zero items match, the looser constraint is
    dropped first (time before budget when prefer_speed, otherwise the
    reverse) and a new query is run.
    """
    await _get_owner_or_404(db, owner_id)

    # Defensive: tier is one of the known values or None
    if tier is not None and tier not in VALID_TIERS:
        raise HTTPException(400, f"tier must be one of {sorted(VALID_TIERS)}")

    tag_list: List[str] = []
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    elif tag:
        tag_list = [tag.strip()]

    async def _query(
        bmax: Optional[float], pmax: Optional[int], t: Optional[str]
    ) -> List[CatalogItem]:
        stmt = select(CatalogItem).where(
            CatalogItem.owner_id == owner_id,
            CatalogItem.available.is_(True),
        )
        if bmax is not None:
            stmt = stmt.where(CatalogItem.price <= bmax)
        if pmax is not None:
            stmt = stmt.where(CatalogItem.prep_time_minutes <= pmax)
        if t is not None:
            stmt = stmt.where(CatalogItem.prep_time_tier == t)
        if category:
            stmt = stmt.where(CatalogItem.category == category)
        if tag_list:
            if require_all_tags:
                for tg in tag_list:
                    stmt = stmt.where(CatalogItem.tags.contains([tg]))
            else:
                # Match any tag — use JSON LIKE-style substring match
                # (works for SQLite + PG; we filter post-query for safety)
                pass
        stmt = stmt.order_by(
            CatalogItem.priority.desc(),
            CatalogItem.popularity_score.desc(),
            CatalogItem.margin.desc(),
            CatalogItem.prep_time_minutes.asc(),
        )
        res = await db.execute(stmt)
        items = list(res.scalars().all())
        if tag_list and not require_all_tags:
            items = [
                it for it in items
                if it.tags and any(t in it.tags for t in tag_list)
            ]
        return items

    items = await _query(budget_max, prep_time_max_minutes, tier)

    if not items and relax:
        # Get the owner's relaxation policy
        pol_res = await db.execute(select(Policy).where(Policy.owner_id == owner_id))
        policy = pol_res.scalar_one_or_none()
        relax_pref = policy.relaxation_policy if policy else "prefer_speed"

        # Pick which constraint to drop first
        if relax_pref == "prefer_speed":
            # Relax prep time first (drop the time cap)
            items = await _query(budget_max, None, tier)
            if not items and budget_max is not None:
                # Then drop budget too
                items = await _query(None, None, tier)
        elif relax_pref == "prefer_budget":
            # Relax budget first
            items = await _query(None, prep_time_max_minutes, tier)
            if not items and prep_time_max_minutes is not None:
                items = await _query(None, None, tier)
        else:  # strict — no relaxation
            pass

    return items


# ─── Routes: Policies ─────────────────────────────────────────────────

@router.put("/owners/{owner_id}/policies", response_model=PolicyOut)
async def upsert_policy(
    owner_id: int,
    payload: PolicyCreate,
    db: AsyncSession = Depends(_get_db),
) -> Policy:
    await _get_owner_or_404(db, owner_id)
    res = await db.execute(select(Policy).where(Policy.owner_id == owner_id))
    policy = res.scalar_one_or_none()
    data = payload.model_dump()
    if policy is None:
        policy = Policy(owner_id=owner_id, **data)
        db.add(policy)
    else:
        for k, v in data.items():
            setattr(policy, k, v)
    await db.commit()
    await db.refresh(policy)
    return policy


# ─── Routes: API keys (encrypted) ────────────────────────────────────

@router.post(
    "/owners/{owner_id}/keys",
    response_model=ApiKeyOut,
    status_code=201,
)
async def add_api_key(
    owner_id: int,
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(_get_db),
) -> OwnerApiKey:
    """Store a third-party API key. The plaintext is encrypted at rest
    and is NEVER returned by any subsequent GET — only `key_mask`."""
    await _get_owner_or_404(db, owner_id)
    if not payload.key and not payload.secret:
        raise HTTPException(400, "at least one of key/secret is required")

    enc_key = encrypt_value(payload.key) if payload.key else None
    enc_secret = encrypt_value(payload.secret) if payload.secret else None
    mask = _mask_key(payload.key or payload.secret or "")

    record = OwnerApiKey(
        owner_id=owner_id,
        provider=payload.provider,
        key_id=payload.key_id,
        encrypted_key=enc_key,
        encrypted_secret=enc_secret,
        key_mask=mask,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


@router.get("/owners/{owner_id}/keys", response_model=List[ApiKeyOut])
async def list_api_keys(
    owner_id: int, db: AsyncSession = Depends(_get_db)
) -> List[OwnerApiKey]:
    """List stored API keys. NEVER returns plaintext — only mask + provider."""
    await _get_owner_or_404(db, owner_id)
    res = await db.execute(
        select(OwnerApiKey).where(OwnerApiKey.owner_id == owner_id)
    )
    return list(res.scalars().all())


# ─── Internal helper for Section 3 ────────────────────────────────────

async def fetch_owner_context(db: AsyncSession, owner_id: int) -> dict:
    """Return the full context bundle the Section 3 reply engine will
    need for one owner: profile, policy, and a small ranked catalog
    sample. Exported so Section 3 can call it without re-implementing."""
    owner = await _get_owner_or_404(db, owner_id)
    pol_res = await db.execute(select(Policy).where(Policy.owner_id == owner_id))
    policy = pol_res.scalar_one_or_none()
    return {
        "owner_id": owner.id,
        "business_name": owner.business_name,
        "business_category": owner.business_category,
        "brand_voice": owner.brand_voice,
        "languages": owner.languages or ["en"],
        "currency": owner.currency,
        "policy": {
            "relaxation_policy": policy.relaxation_policy,
            "fastest_guarantee_minutes": policy.fastest_guarantee_minutes,
            "max_autonomous_discount_pct": policy.max_autonomous_discount_pct,
            "max_autonomous_substitution": policy.max_autonomous_substitution,
        } if policy else None,
    }
