"""
Database module - Uses PostgreSQL if available, falls back to SQLite for standalone testing.
For full functionality, run Docker with: docker-compose up -d
"""
import os
import json
import logging
os.environ['SQLALCHEMY_SKIP_PLATFORM_CHECK'] = '1'  # Fix for Windows

logger = logging.getLogger("db")

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, JSON, ForeignKey, select
from crypto_fields import EncryptedString, hmac_phone_hash
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
import os

# Try PostgreSQL first, fallback to SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    # Use user temp directory to avoid permission issues
    temp_dir = os.environ.get('TEMP', 'C:\\temp')
    DB_PATH = os.path.join(temp_dir, "wap", "wap_data.db")
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    # Convert to forward slashes for SQLite URL on Windows
    DB_PATH_URL = DB_PATH.replace("\\", "/")
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH_URL}"
    print(f"[i] Using database: {DATABASE_URL}")
else:
    print(f"[i] Using database from env: {DATABASE_URL}")

print(f"[i] Using database: {DATABASE_URL.split('://')[0]}")

# Connection pool settings to prevent idle timeouts
engine_args = {
    "echo": False,
    "pool_size": 20,
    "max_overflow": 10,
    "pool_pre_ping": True,        # Verify connections before use
    "pool_recycle": 300,          # Recycle connections every 5 minutes
    "pool_timeout": 30,           # Timeout getting connection from pool
}

# Add PostgreSQL-specific settings
if DATABASE_URL.startswith("postgresql"):
    engine_args.update({
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_timeout": 30,
        "connect_args": {
            "server_settings": {
                "application_name": "whatsapp_agent",
                "tcp_keepalives_idle": "300",
                "tcp_keepalives_interval": "30",
                "tcp_keepalives_count": "3",
            },
            "command_timeout": 60,
        }
    })

print(f"[i] Creating engine with URL: {DATABASE_URL}")
print(f"[i] Engine args: {engine_args}")
engine = create_async_engine(DATABASE_URL, **engine_args)
print(f"[i] Engine created successfully")
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
print(f"[i] Async session maker created")


class Base(DeclarativeBase):
    pass


class Client(Base):
    """Multi-tenant client/business entity."""
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_name: Mapped[str] = mapped_column(String(255))
    vertical: Mapped[str] = mapped_column(String(20), default="general")  # doctor/lawyer/ca/restaurant
    whatsapp_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(20), default="trial")  # trial/basic/pro
    is_active: Mapped[bool] = mapped_column(default=True)
    business_profile: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)  # menu/services/pricing/brand-voice for per-shop LLM prompt
    qr_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # per-client QR scan tracking on/off
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    phone_number: Mapped[str] = mapped_column(EncryptedString(255))  # encrypted at rest
    phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # lookup key
    contact_name: Mapped[Optional[str]] = mapped_column(String(255))
    session_id: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="active")
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("conversations.id"), index=True)
    phone_number: Mapped[str] = mapped_column(EncryptedString(255))  # encrypted at rest
    phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # lookup key
    message_type: Mapped[str] = mapped_column(String(20), default="text")
    content: Mapped[Optional[str]] = mapped_column(Text)
    media_url: Mapped[Optional[str]] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(10), default="incoming")
    status: Mapped[str] = mapped_column(String(20), default="received")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    phone_number: Mapped[str] = mapped_column(EncryptedString(255))  # encrypted at rest
    phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # lookup key
    name: Mapped[Optional[str]] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    lead_score: Mapped[int] = mapped_column(Integer, default=0)
    lead_status: Mapped[str] = mapped_column(String(20), default="new")
    source: Mapped[Optional[str]] = mapped_column(String(50))
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"))
    phone_number: Mapped[str] = mapped_column(EncryptedString(255))  # encrypted at rest
    phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # lookup key
    title: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    appointment_date: Mapped[Optional[str]] = mapped_column(String(20))
    appointment_time: Mapped[Optional[str]] = mapped_column(String(20))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    sector_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Booking(Base):
    """Generic booking/order from web chat widget or other channels."""
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"))
    business_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    business_type: Mapped[str] = mapped_column(String(50), default="general")
    intent: Mapped[str] = mapped_column(String(50), default="booking_request")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    date: Mapped[Optional[str]] = mapped_column(String(20))
    time: Mapped[Optional[str]] = mapped_column(String(20))
    party_size: Mapped[Optional[int]] = mapped_column(Integer)
    service_type: Mapped[Optional[str]] = mapped_column(String(255))
    customer_name: Mapped[Optional[str]] = mapped_column(String(255))
    customer_contact: Mapped[Optional[str]] = mapped_column(EncryptedString(255))  # encrypted at rest
    notes: Mapped[Optional[str]] = mapped_column(Text)
    raw_extracted: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(50), default="web_chat")
    conversation_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)  # idempotency key (dedup retries)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "contact_id": self.contact_id,
            "business_id": self.business_id,
            "business_type": self.business_type,
            "intent": self.intent,
            "status": self.status,
            "date": self.date,
            "time": self.time,
            "party_size": self.party_size,
            "service_type": self.service_type,
            "customer_name": self.customer_name,
            "customer_contact": self.customer_contact,
            "notes": self.notes,
            "raw_extracted": self.raw_extracted,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConversationSession(Base):
    """Persistent conversation session for slot-filling and context."""
    __tablename__ = "conversation_sessions"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    phone_number: Mapped[str] = mapped_column(EncryptedString(255))  # encrypted at rest
    phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # lookup key
    session_state: Mapped[str] = mapped_column(String(50), default="browsing")
    intent: Mapped[Optional[str]] = mapped_column(String(50))
    entities: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    slot_data: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    context: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    last_user_message: Mapped[Optional[str]] = mapped_column(Text)
    last_bot_message: Mapped[Optional[str]] = mapped_column(Text)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    is_human_takeover: Mapped[bool] = mapped_column(default=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))



# -- Seller CRM models (Amazon / Flipkart) --

class SellerProduct(Base):
    __tablename__ = "seller_products"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True, default=1)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    cogs: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class SellerListing(Base):
    __tablename__ = "seller_listings"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True, default=1)
    product_id: Mapped[int] = mapped_column(ForeignKey("seller_products.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    listing_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(Text)
    bullets: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    backend_keywords: Mapped[Optional[str]] = mapped_column(String(500))
    price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    seo_score: Mapped[float] = mapped_column(Float, default=0.0)
    seo_issues: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_audited_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class SellerOrder(Base):
    __tablename__ = "seller_orders"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True, default=1)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("seller_products.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255))
    customer_phone: Mapped[Optional[str]] = mapped_column(EncryptedString(255))  # encrypted at rest
    customer_phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)  # lookup key
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    tax: Mapped[float] = mapped_column(Float, default=0.0)
    shipping: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    payment_status: Mapped[str] = mapped_column(String(50), default="pending")
    fulfillment_status: Mapped[str] = mapped_column(String(50), default="unfulfilled")
    shipping_address: Mapped[Optional[str]] = mapped_column(Text)
    tracking_id: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True, default=1)
    product_id: Mapped[int] = mapped_column(ForeignKey("seller_products.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    my_price: Mapped[float] = mapped_column(Float)
    competitor_price: Mapped[float] = mapped_column(Float)
    competitor_name: Mapped[Optional[str]] = mapped_column(String(255))
    price_delta: Mapped[float] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class SeoAudit(Base):
    __tablename__ = "seo_audits"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True, default=1)
    listing_id: Mapped[int] = mapped_column(ForeignKey("seller_listings.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    issues: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    suggestions: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    keywords_found: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    keywords_missing: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True, default=1)
    product_id: Mapped[int] = mapped_column(ForeignKey("seller_products.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    alert_type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    my_price: Mapped[float] = mapped_column(Float)
    competitor_price: Mapped[float] = mapped_column(Float)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

# ──────────────────────────────────────────────────────────────────────
# Multi-Tenant Owner Onboarding (Section 2)
# Owner = the business that signs up. Client = the existing row in
# `clients` that represents their WhatsApp number routing. We keep both
# so we don't have to migrate the 19 existing messages.
# Every row below MUST carry owner_id; tenant isolation is enforced in
# the route layer and every query in onboarding.py.
# ──────────────────────────────────────────────────────────────────────

class Owner(Base):
    """Owner = business that signs up via the onboarding wizard.

    One-to-one with `Client` via `client_id` (a Client may exist before
    the Owner does; we link them after onboarding completes).
    """
    __tablename__ = "owners"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), index=True)

    # Identity / auth
    business_name: Mapped[str] = mapped_column(String(255))
    owner_name: Mapped[str] = mapped_column(String(255))
    owner_phone: Mapped[str] = mapped_column(EncryptedString(255))
    owner_phone_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255))
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))  # bcrypt
    business_category: Mapped[str] = mapped_column(String(50), default="general")
    # restaurant / clinic / salon / retail / agency / doctor / lawyer / ca / other

    # Business profile
    address: Mapped[Optional[str]] = mapped_column(Text)
    business_hours: Mapped[Optional[str]] = mapped_column(String(255))  # e.g. "Mon-Sat 9am-9pm"
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    languages: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)  # ["hi","en"]
    brand_voice: Mapped[str] = mapped_column(String(20), default="casual")  # formal / casual / playful
    currency: Mapped[str] = mapped_column(String(8), default="INR")

    # Escalation / ops
    escalation_contact: Mapped[Optional[str]] = mapped_column(String(255))
    escalation_channel: Mapped[Optional[str]] = mapped_column(String(20))  # whatsapp / slack / email
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String(8))  # "22:00"
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String(8))    # "08:00"

    # Onboarding state
    is_active: Mapped[bool] = mapped_column(default=True)
    onboarded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class CatalogItem(Base):
    """An item the owner offers — menu item, service, SKU, etc.

    Every row is scoped to one Owner (tenant isolation). Ranking is a
    composite of priority (owner-set) + popularity_score (incremented
    on orders) + margin. Section 3 reads this table.
    """
    __tablename__ = "catalog_items"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True)

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    prep_time_minutes: Mapped[int] = mapped_column(Integer, default=15)
    prep_time_tier: Mapped[str] = mapped_column(String(10), default="normal")  # fast / normal / slow
    category: Mapped[Optional[str]] = mapped_column(String(100))
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)  # veg, popular, budget, etc.

    available: Mapped[bool] = mapped_column(Boolean, default=True)
    popularity_score: Mapped[int] = mapped_column(Integer, default=0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0–1.0, used for ranking tie-breaks
    priority: Mapped[int] = mapped_column(Integer, default=0)  # owner-set, higher = shown first

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Policy(Base):
    """Per-owner business policies. One-to-one with Owner.

    `relaxation_policy` and `max_autonomous_discount_pct` are what the
    Section 3 reply engine consults to decide whether to relax a
    constraint, offer a discount, or escalate to a human.
    """
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True, unique=True)

    refund_policy: Mapped[Optional[str]] = mapped_column(Text)
    cancellation_policy: Mapped[Optional[str]] = mapped_column(Text)
    delivery_radius_km: Mapped[Optional[float]] = mapped_column(Float)
    min_order_amount: Mapped[Optional[float]] = mapped_column(Float)
    discount_rules: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    quiet_hours: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Section-3 knobs
    relaxation_policy: Mapped[str] = mapped_column(String(20), default="prefer_speed")
    # prefer_speed (relax time first) / prefer_budget (relax time last) / strict (no relaxation)
    fastest_guarantee_minutes: Mapped[int] = mapped_column(Integer, default=15)
    max_autonomous_discount_pct: Mapped[float] = mapped_column(Float, default=5.0)
    max_autonomous_substitution: Mapped[bool] = mapped_column(Boolean, default=True)
    escalation_triggers: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class OwnerApiKey(Base):
    """Encrypted third-party API keys per owner (WhatsApp, payments, etc.).

    The plaintext is encrypted at rest via EncryptedString. The
    `key_mask` is what the owner sees in the dashboard — a short
    fingerprint, never the full key. The full plaintext is never
    returned by any GET route after the initial insert.
    """
    __tablename__ = "owner_api_keys"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("owners.id"), index=True)

    provider: Mapped[str] = mapped_column(String(50))  # whatsapp_business / razorpay / stripe / google_calendar
    key_id: Mapped[Optional[str]] = mapped_column(String(255))  # public identifier (e.g. rzp_test_xxx)
    encrypted_key: Mapped[Optional[str]] = mapped_column(EncryptedString(2048))
    encrypted_secret: Mapped[Optional[str]] = mapped_column(EncryptedString(2048))
    key_mask: Mapped[str] = mapped_column(String(40))  # e.g. "****aB12" — safe to display

    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# NOTE: Broadcast models are intentionally NOT imported here at module scope.
# broadcast.py imports from db (Base, async_session) at module scope, so a
# module-level `from broadcast import ...` can trip a "partially initialized
# module" ImportError depending on import order. They are exposed lazily via
# the module __getattr__ below, and registered eagerly in init_db/register.
def __getattr__(name):
    """PEP 562 lazy attributes (avoid circular imports at module scope)."""
    if name == "Lead":
        from lead_gen import Lead
        return Lead
    if name in ("BroadcastList", "BroadcastCampaign"):
        import broadcast as _broadcast
        return getattr(_broadcast, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def register_loop_models():
    """Lazy import of Phase 3 loop + extension models, then create any
    tables that were not yet part of Base.metadata when init_db() ran.

    Without this final create_all pass, models imported lazily here (loops,
    QA logs, advisory turns) would never get their tables on a fresh DB.
    """
    from lead_gen import Lead                        # noqa: F401 - register leads table
    from broadcast import (                          # noqa: F401 - register broadcast tables
        BroadcastList, BroadcastCampaign, ContactList,
        ContactListMember, CampaignSend,
    )
    from lead_funnel import LeadFunnelEnrollment      # noqa: F401
    from appointment_nurture import AppointmentNurtureEnrollment  # noqa: F401
    from compliance_loop import ConsentRecordDB, DataRetentionLog  # noqa: F401
    from reengagement_loop import ReengagementLog     # noqa: F401
    from db_extensions import CompanyReport, QALog, AdvisoryTurn  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _sync_sqlite_columns(conn)


async def _sync_sqlite_columns(conn) -> None:
    """Dev-DB safety net: create_all does NOT add columns to existing SQLite
    tables, so models that gained fields (e.g. Appointment.phone_hash) fail
    on flush against an older dev database. Add missing columns idempotently."""
    from sqlalchemy import text
    if not str(engine.url).startswith("sqlite"):
        return
    for table in Base.metadata.tables.values():
        rows = (await conn.execute(
            text(f"PRAGMA table_info({table.name})"))).fetchall()
        existing = {r[1] for r in rows}
        if not existing:
            continue
        for col in table.columns:
            if col.name in existing:
                continue
            try:
                coltype = col.type.compile(dialect=engine.dialect)
            except Exception:
                coltype = "TEXT"
            await conn.execute(text(
                f"ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}"))
            logger.info("Added missing column %s.%s (dev DB drift)",
                        table.name, col.name)


async def get_session():
    async with async_session() as session:
        yield session


async def init_db():
    print(f"[i] Initializing database...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"[i] Database tables created/verified")
    print("[v] Database tables created/verified")


async def save_message(session, phone_number, content, direction="incoming", message_type="text",
                        client_id: int = 1):
    phone_h = hmac_phone_hash(phone_number)
    result = await session.execute(
        select(Conversation).where(Conversation.phone_hash == phone_h,
                                   Conversation.client_id == client_id)
        .order_by(Conversation.last_message_at.desc()).limit(1)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        conversation = Conversation(phone_number=phone_number, phone_hash=phone_h, status="active", client_id=client_id)
        session.add(conversation)
        await session.flush()
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.unread_count = (conversation.unread_count or 0) + 1 if direction == "incoming" else 0
    message = Message(conversation_id=conversation.id, phone_number=phone_number, phone_hash=phone_h,
                      content=content, direction=direction, message_type=message_type,
                      client_id=client_id)
    session.add(message)
    await session.commit()
    return message


async def get_conversation_history(session, phone_number, limit=20, client_id: int = 1):
    phone_h = hmac_phone_hash(phone_number)
    result = await session.execute(
        select(Message).where(Message.phone_hash == phone_h,
                              Message.client_id == client_id)
        .order_by(Message.created_at.desc()).limit(limit)
    )
    messages = result.scalars().all()
    return list(reversed(messages))


async def upsert_contact(session, phone_number, client_id: int = 1, **kwargs):
    phone_h = hmac_phone_hash(phone_number)
    result = await session.execute(
        select(Contact).where(Contact.phone_hash == phone_h,
                              Contact.client_id == client_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        contact = Contact(phone_number=phone_number, phone_hash=phone_h, client_id=client_id, **kwargs)
        session.add(contact)
    else:
        for key, value in kwargs.items():
            if value is not None:
                setattr(contact, key, value)
        contact.phone_hash = phone_h
    await session.commit()
    return contact


# -- Multi-tenant client functions --

async def get_client_by_whatsapp_number(session, whatsapp_number: str):
    """Look up which client owns a given WhatsApp number (for message routing)."""
    result = await session.execute(
        select(Client).where(Client.whatsapp_number == whatsapp_number,
                             Client.is_active == True)
    )
    return result.scalar_one_or_none()


async def create_client(session, business_name: str, whatsapp_number: str,
                        vertical: str = "general", plan: str = "trial") -> Client:
    """Create a new client/business."""
    client = Client(business_name=business_name, whatsapp_number=whatsapp_number,
                    vertical=vertical, plan=plan)
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client


async def get_client_usage(session, client_id: int):
    """Get usage stats for a client (messages, appointments, contacts)."""
    from sqlalchemy import func
    msg_count = await session.execute(
        select(func.count()).select_from(Message).where(Message.client_id == client_id)
    )
    appt_count = await session.execute(
        select(func.count()).select_from(Appointment).where(Appointment.client_id == client_id)
    )
    contact_count = await session.execute(
        select(func.count()).select_from(Contact).where(Contact.client_id == client_id)
    )
    return {
        "total_messages": msg_count.scalar(),
        "total_appointments": appt_count.scalar(),
        "total_contacts": contact_count.scalar()
    }


# -- Conversation session helpers (1.1 persistent memory, 1.5 isolation) --

async def get_or_create_session(session, client_id: int, phone_number: str, ttl_hours: int = 48) -> "ConversationSession":
    """Load existing session or create a fresh one. Returns the session row."""
    phone_h = hmac_phone_hash(phone_number)
    result = await session.execute(
        select(ConversationSession).where(
            ConversationSession.client_id == client_id,
            ConversationSession.phone_hash == phone_h,
            ConversationSession.is_human_takeover == False,
        ).order_by(ConversationSession.last_activity_at.desc()).limit(1)
    )
    conv_session = result.scalar_one_or_none()
    if not conv_session:
        conv_session = ConversationSession(client_id=client_id, phone_number=phone_number, phone_hash=phone_h)
        session.add(conv_session)
        await session.flush()
        return conv_session

    # Auto-reset if idle beyond TTL (1.5)
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    idle = now - conv_session.last_activity_at
    if idle > timedelta(hours=ttl_hours):
        conv_session.session_state = "browsing"
        conv_session.intent = None
        conv_session.entities = {}
        conv_session.slot_data = {}
        conv_session.context = {}
        conv_session.last_user_message = None
        conv_session.last_bot_message = None
        conv_session.message_count = 0
        conv_session.is_human_takeover = False
        conv_session.updated_at = now

    conv_session.last_activity_at = now
    await session.commit()
    await session.refresh(conv_session)
    return conv_session


async def update_session_after_message(session, client_id: int, phone_number: str, user_message: str, bot_message: str, intent: str, entities: dict, slot_data: dict, new_state: str):
    """Append a turn to the conversation session."""
    phone_h = hmac_phone_hash(phone_number)
    result = await session.execute(
        select(ConversationSession).where(
            ConversationSession.client_id == client_id,
            ConversationSession.phone_hash == phone_h,
        ).order_by(ConversationSession.last_activity_at.desc()).limit(1)
    )
    conv_session = result.scalar_one_or_none()
    if not conv_session:
        conv_session = ConversationSession(client_id=client_id, phone_number=phone_number, phone_hash=phone_h)
        session.add(conv_session)

    conv_session.last_user_message = user_message
    conv_session.last_bot_message = bot_message
    conv_session.intent = intent
    conv_session.entities = entities
    conv_session.slot_data = slot_data
    conv_session.session_state = new_state
    conv_session.message_count = (conv_session.message_count or 0) + 1
    conv_session.last_activity_at = datetime.now(timezone.utc)
    conv_session.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(conv_session)
    return conv_session


# -- Booking helpers for web chat widget --

def booking_idempotency_key(client_id: int, business_id: str, extracted: dict) -> str:
    """Deterministic idempotency key for a booking request.

    Built from the customer + slot + service so a duplicate retry of the same
    booking (e.g. a WhatsApp/web retry of an identical message) deduplicates.
    """
    import hashlib
    fingerprint = {
        "client_id": client_id,
        "business_id": business_id,
        "customer_contact": (extracted or {}).get("customer_contact"),
        "date": (extracted or {}).get("date"),
        "time": (extracted or {}).get("time"),
        "service_type": (extracted or {}).get("service_type"),
        "intent": (extracted or {}).get("intent", "booking_request"),
    }
    raw = json.dumps(fingerprint, sort_keys=True, default=str)
    return "bk_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


async def create_booking(session, client_id: int, business_id: str, business_type: str,
                         extracted: dict, source: str = "web_chat",
                         conversation_id: Optional[str] = None) -> "Booking":
    """Create a booking row from LLM-extracted fields.

    Idempotent: retries carrying the same conversation_id (or the same
    customer + slot + service fingerprint) reuse the existing row instead of
    inserting a duplicate.
    """
    conv_id = conversation_id or booking_idempotency_key(client_id, business_id, extracted)

    # Idempotency check — dedup retries of the same booking.
    existing = await session.execute(
        select(Booking).where(
            Booking.conversation_id == conv_id,
            Booking.client_id == client_id,
        ).limit(1)
    )
    found = existing.scalar_one_or_none()
    if found is not None:
        logger.info("[i] Reusing existing booking id=%s for conversation_id=%s", found.id, conv_id)
        return found

    booking = Booking(
        client_id=client_id,
        business_id=business_id,
        business_type=business_type,
        intent=extracted.get("intent", "booking_request"),
        date=extracted.get("date"),
        time=extracted.get("time"),
        party_size=extracted.get("party_size"),
        service_type=extracted.get("service_type"),
        customer_name=extracted.get("customer_name"),
        customer_contact=extracted.get("customer_contact"),
        notes=extracted.get("notes"),
        raw_extracted=extracted,
        source=source,
        conversation_id=conv_id,
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking)
    return booking


async def get_bookings(client_id: int, business_id: str = "", limit: int = 50):
    """List bookings for a client/business."""
    async with async_session() as session:
        query = select(Booking).where(Booking.client_id == client_id)
        if business_id:
            query = query.where(Booking.business_id == business_id)
        query = query.order_by(Booking.created_at.desc()).limit(limit)
        result = await session.execute(query)
        bookings = result.scalars().all()
        return [b.to_dict() for b in bookings]


class DeadLetterJob(Base):
    __tablename__ = "dead_letter_jobs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(100))
    args: Mapped[Optional[str]] = mapped_column(Text)
    kwargs: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    failed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


async def create_dead_letter_job(session, task_name: str, args: list, kwargs: dict, error: str, retries: int):
    job = DeadLetterJob(
        task_name=task_name,
        args=json.dumps(args),
        kwargs=json.dumps(kwargs),
        error=error,
        retries=retries,
    )
    session.add(job)
    await session.commit()
    return job


# ──────────────────────────────────────────────────────────────────────
# Lead → Order pipeline (Lead Visibility + Order Processing)
# ──────────────────────────────────────────────────────────────────────

class Order(Base):
    """A sale/order converted from a lead/contact."""
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), index=True)
    lead_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    description: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "client_id": self.client_id, "contact_id": self.contact_id,
            "lead_id": self.lead_id, "amount": self.amount, "currency": self.currency,
            "status": self.status, "description": self.description, "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class QRScan(Base):
    """A scan of a shop's QR code (poster/flyer/table-tent referral tag)."""
    __tablename__ = "qr_scans"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    tag: Mapped[str] = mapped_column(String(64), index=True)  # campaign/placement tag
    source: Mapped[Optional[str]] = mapped_column(String(32))  # poster|flyer|table|web|...
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))  # rate-limit/abuse key
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))
    meta: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "id": self.id, "client_id": self.client_id, "tag": self.tag,
            "source": self.source, "created_at": self.created_at.isoformat()
            if self.created_at else None,
            **(self.meta or {}),
        }


async def create_qr_scan(client_id: int, tag: str, source: str = "",
                         ip_hash: str = "", user_agent: str = "",
                         meta: Optional[dict] = None) -> QRScan:
    """Record a QR scan (public endpoint path)."""
    async with async_session() as session:
        scan = QRScan(client_id=client_id, tag=tag, source=source or None,
                      ip_hash=ip_hash or None, user_agent=user_agent[:255] or None,
                      meta=meta or {})
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        return scan


async def qr_report(client_id: int, days: int = 30) -> Dict:
    """Aggregated QR-scan report: totals per tag and per day."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with async_session() as session:
        rows = (await session.execute(
            select(QRScan).where(QRScan.client_id == client_id,
                                 QRScan.created_at >= since)
            .order_by(QRScan.created_at.desc()).limit(5000))).scalars().all()
    by_tag: Dict[str, int] = {}
    by_day: Dict[str, int] = {}
    for r in rows:
        by_tag[r.tag] = by_tag.get(r.tag, 0) + 1
        day = r.created_at.strftime("%Y-%m-%d") if r.created_at else "unknown"
        by_day[day] = by_day.get(day, 0) + 1
    return {
        "client_id": client_id, "days": days, "total": len(rows),
        "by_tag": dict(sorted(by_tag.items(), key=lambda kv: -kv[1])),
        "by_day": dict(sorted(by_day.items())),
        "recent": [r.to_dict() for r in rows[:25]],
    }


async def qr_tracking_enabled(client_id: int) -> bool:
    """Per-client enable/disable flag for QR tracking."""
    async with async_session() as session:
        res = await session.execute(
            select(Client.qr_tracking_enabled).where(Client.id == client_id))
        val = res.scalar_one_or_none()
        return bool(val) if val is not None else True


async def get_client_by_whatsapp_number(whatsapp_number: str) -> Optional[Client]:
    """Resolve a client_id from a WhatsApp number (bridge uses this on inbound)."""
    async with async_session() as session:
        res = await session.execute(
            select(Client).where(Client.whatsapp_number == whatsapp_number))
        return res.scalar_one_or_none()


async def list_leads(client_id: int, status: str = "", limit: int = 50, offset: int = 0) -> List[Dict]:
    """Paginated leads (contacts) for a client, optionally filtered by lead_status."""
    async with async_session() as session:
        query = select(Contact).where(Contact.client_id == client_id)
        if status:
            query = query.where(Contact.lead_status == status)
        query = query.order_by(Contact.updated_at.desc()).offset(offset).limit(limit)
        rows = (await session.execute(query)).scalars().all()
        return [{
            "id": c.id, "name": c.name, "phone": c.phone_number,
            "email": c.email, "tags": c.tags or [], "notes": c.notes,
            "lead_score": c.lead_score, "lead_status": c.lead_status,
            "source": c.source, "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        } for c in rows]


async def get_lead_messages(client_id: int, contact_id: int, limit: int = 100) -> List[Dict]:
    """Full message thread for a lead, scoped to the client (tenant-safe)."""
    async with async_session() as session:
        res = await session.execute(
            select(Message).where(
                Message.client_id == client_id,
                Message.phone_hash == select(Contact.phone_hash).where(
                    Contact.id == contact_id, Contact.client_id == client_id).scalar_subquery(),
            ).order_by(Message.created_at.asc()).limit(limit))
        rows = res.scalars().all()
        return [{
            "id": m.id, "direction": m.direction, "content": m.content,
            "message_type": m.message_type, "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        } for m in rows]


async def update_lead_status(client_id: int, contact_id: int, status: str) -> Optional[Contact]:
    """Mark a lead: new/contacted/qualified/won/lost. Tenant-scoped."""
    allowed = {"new", "contacted", "qualified", "won", "lost"}
    if status not in allowed:
        raise ValueError(f"status must be one of {allowed}")
    async with async_session() as session:
        res = await session.execute(
            select(Contact).where(Contact.id == contact_id, Contact.client_id == client_id))
        contact = res.scalar_one_or_none()
        if contact:
            contact.lead_status = status
            contact.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(contact)
        return contact


async def create_order(client_id: int, contact_id: int, amount: float,
                       currency: str = "INR", description: str = "", notes: str = "") -> Order:
    """Convert a lead into an order/sale (link back to contact/lead)."""
    async with async_session() as session:
        order = Order(
            client_id=client_id, contact_id=contact_id, lead_id=contact_id,
            amount=amount, currency=currency, status="pending",
            description=description, notes=notes,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        return order


async def get_orders(client_id: int, status: str = "", limit: int = 50) -> List[Dict]:
    """Orders for a client, optional status filter."""
    async with async_session() as session:
        query = select(Order).where(Order.client_id == client_id)
        if status:
            query = query.where(Order.status == status)
        query = query.order_by(Order.created_at.desc()).limit(limit)
        return [o.to_dict() for o in (await session.execute(query)).scalars().all()]


async def admin_overview() -> Dict:
    """Platform-wide stats for the multi-tenant admin dashboard."""
    from sqlalchemy import func
    async with async_session() as session:
        total_clients = (await session.execute(select(func.count(Client.id)))).scalar() or 0
        active_clients = (await session.execute(
            select(func.count(Client.id)).where(Client.is_active.is_(True)))).scalar() or 0
        total_leads = (await session.execute(select(func.count(Contact.id)))).scalar() or 0
        total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
        paid = (await session.execute(
            select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "paid"))).scalar() or 0
        return {
            "total_clients": int(total_clients),
            "active_clients": int(active_clients),
            "inactive_clients": int(total_clients - active_clients),
            "total_leads": int(total_leads),
            "total_orders": int(total_orders),
            "monthly_revenue": float(paid),
        }


async def create_indexes():
    """Create indexes on hot-read columns for messages, appointments, bookings, conversation_sessions."""
    from sqlalchemy import text
    index_statements = [
        "ALTER TABLE bookings ADD COLUMN conversation_id VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_conversation_id ON bookings (conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_phone_number ON messages (phone_number)",
        "CREATE INDEX IF NOT EXISTS idx_messages_client_id ON messages (client_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages (conversation_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages (created_at)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_client_id ON appointments (client_id)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_phone_number ON appointments (phone_number)",
        "CREATE INDEX IF NOT EXISTS idx_appointments_created_at ON appointments (created_at)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_client_id ON bookings (client_id)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_created_at ON bookings (created_at)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_client_id ON conversation_sessions (client_id)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_phone_number ON conversation_sessions (phone_number)",
        "CREATE INDEX IF NOT EXISTS idx_conversation_sessions_created_at ON conversation_sessions (created_at)",
    ]
    async with engine.begin() as conn:
        for stmt in index_statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass