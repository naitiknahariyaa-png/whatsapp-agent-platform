"""
Database module - Uses PostgreSQL if available, falls back to SQLite for standalone testing.
For full functionality, run Docker with: docker-compose up -d
"""
import os
os.environ['SQLALCHEMY_SKIP_PLATFORM_CHECK'] = '1'  # Fix for Windows

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, Integer, DateTime, JSON, ForeignKey, select
from datetime import datetime, timezone
from typing import Optional, List
import os

# Try PostgreSQL first, fallback to SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    # Use absolute path to avoid DB being created in wrong directory
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wap_data.db")
    DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

print(f"[i] Using database: {DATABASE_URL.split('://')[0]}")

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
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
    conversation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("conversations.id"))
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
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
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
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
    phone_number: Mapped[str] = mapped_column(String(20))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    appointment_date: Mapped[Optional[str]] = mapped_column(String(20))
    appointment_time: Mapped[Optional[str]] = mapped_column(String(20))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    calendar_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


async def get_session():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[v] Database tables created/verified")


async def save_message(session, phone_number, content, direction="incoming", message_type="text",
                       client_id: int = 1):
    result = await session.execute(
        select(Conversation).where(Conversation.phone_number == phone_number,
                                   Conversation.client_id == client_id)
        .order_by(Conversation.last_message_at.desc()).limit(1)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        conversation = Conversation(phone_number=phone_number, status="active", client_id=client_id)
        session.add(conversation)
        await session.flush()
    conversation.last_message_at = datetime.now(timezone.utc)
    conversation.unread_count = (conversation.unread_count or 0) + 1 if direction == "incoming" else 0
    message = Message(conversation_id=conversation.id, phone_number=phone_number,
                      content=content, direction=direction, message_type=message_type,
                      client_id=client_id)
    session.add(message)
    await session.commit()
    return message


async def get_conversation_history(session, phone_number, limit=20, client_id: int = 1):
    result = await session.execute(
        select(Message).where(Message.phone_number == phone_number,
                              Message.client_id == client_id)
        .order_by(Message.created_at.desc()).limit(limit)
    )
    messages = result.scalars().all()
    return list(reversed(messages))


async def upsert_contact(session, phone_number, client_id: int = 1, **kwargs):
    result = await session.execute(
        select(Contact).where(Contact.phone_number == phone_number,
                              Contact.client_id == client_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        contact = Contact(phone_number=phone_number, client_id=client_id, **kwargs)
        session.add(contact)
    else:
        for key, value in kwargs.items():
            if value is not None:
                setattr(contact, key, value)
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