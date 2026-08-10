"""
Broadcasting Engine — async queue-based bulk messaging.
Sends via the WhatsApp bridge HTTP /send endpoint.
No Redis/BullMQ dependency — uses asyncio.Queue + SQLite for persistence.
"""
import asyncio
import httpx
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, Integer, DateTime, JSON

from db import Base, async_session


# ---------------------------------------------------------------------------
# DB Models
# ---------------------------------------------------------------------------

class BroadcastList(Base):
    __tablename__ = "broadcast_lists"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    phones: Mapped[list] = mapped_column(JSON, default=list)  # ["919999999999", ...]
    tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class BroadcastCampaign(Base):
    __tablename__ = "broadcast_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    list_name: Mapped[str] = mapped_column(String(100), index=True)
    message_template: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | completed | failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[Optional[list]] = mapped_column(JSON, default=list)  # per-phone status
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BroadcastEngine:
    """Lightweight async broadcast engine with rate-limiting."""

    def __init__(self, bridge_url: str = "http://localhost:3001", rate_per_sec: float = 1.0):
        self.bridge_url = bridge_url
        self.delay = 1.0 / rate_per_sec  # seconds between messages
        self._running_tasks: Dict[int, asyncio.Task] = {}

    # -- List CRUD ----------------------------------------------------------

    async def create_list(self, name: str, phones: List[str],
                          description: str = "", tags: Optional[List[str]] = None) -> dict:
        async with async_session() as session:
            existing = (await session.execute(
                select(BroadcastList).where(BroadcastList.name == name)
            )).scalar_one_or_none()

            if existing:
                existing.phones = phones
                existing.description = description
                existing.tags = tags or []
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(BroadcastList(
                    name=name, phones=phones, description=description, tags=tags or []
                ))
            await session.commit()
        return {"name": name, "phones_count": len(phones)}

    async def get_lists(self) -> List[dict]:
        async with async_session() as session:
            rows = (await session.execute(select(BroadcastList))).scalars().all()
            return [{"id": r.id, "name": r.name, "phones_count": len(r.phones or []),
                     "tags": r.tags, "description": r.description} for r in rows]

    async def get_list(self, name: str) -> Optional[BroadcastList]:
        async with async_session() as session:
            return (await session.execute(
                select(BroadcastList).where(BroadcastList.name == name)
            )).scalar_one_or_none()

    # -- Campaign -----------------------------------------------------------

    async def send_campaign(self, list_name: str, message_template: str) -> dict:
        """Create a campaign and start sending in the background."""
        bl = await self.get_list(list_name)
        if not bl:
            return {"error": f"List '{list_name}' not found"}

        phones = bl.phones or []
        if not phones:
            return {"error": "List is empty"}

        # Persist campaign
        async with async_session() as session:
            campaign = BroadcastCampaign(
                list_name=list_name,
                message_template=message_template,
                status="pending",
                total=len(phones),
            )
            session.add(campaign)
            await session.commit()
            await session.refresh(campaign)
            campaign_id = campaign.id

        # Fire-and-forget background task
        task = asyncio.create_task(self._run_campaign(campaign_id, phones, message_template))
        self._running_tasks[campaign_id] = task
        return {"campaign_id": campaign_id, "total": len(phones), "status": "started"}

    async def get_campaign(self, campaign_id: int) -> Optional[dict]:
        async with async_session() as session:
            c = (await session.execute(
                select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
            )).scalar_one_or_none()
            if not c:
                return None
            return {
                "id": c.id, "list_name": c.list_name, "status": c.status,
                "total": c.total, "sent": c.sent, "failed": c.failed,
                "results": c.results, "created_at": c.created_at.isoformat(),
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }

    # -- Internal worker ----------------------------------------------------

    async def _run_campaign(self, campaign_id: int, phones: List[str], template: str):
        """Send messages one-by-one with rate-limiting and personalization."""
        results = []
        sent = 0
        failed = 0

        # Mark running
        await self._update_campaign(campaign_id, status="running")

        async with httpx.AsyncClient(timeout=30) as client:
            for phone in phones:
                try:
                    # Personalize message with customer data
                    personalized = await self._personalize_message(phone, template)
                    
                    resp = await client.post(f"{self.bridge_url}/send", json={
                        "to": phone, "message": personalized
                    })
                    if resp.status_code == 200:
                        sent += 1
                        results.append({"phone": phone, "status": "sent", "message": personalized[:100]})
                    else:
                        failed += 1
                        results.append({"phone": phone, "status": "failed", "error": resp.text})
                except Exception as e:
                    failed += 1
                    results.append({"phone": phone, "status": "failed", "error": str(e)})

                # Update progress every message
                await self._update_campaign(campaign_id, sent=sent, failed=failed, results=results)

                # Rate-limit
                await asyncio.sleep(self.delay)

        # Mark completed
        await self._update_campaign(
            campaign_id, status="completed", sent=sent, failed=failed,
            results=results, completed_at=datetime.now(timezone.utc)
        )
        self._running_tasks.pop(campaign_id, None)

    async def _personalize_message(self, phone: str, template: str) -> str:
        """Personalize message with customer name and order history"""
        from db import upsert_contact, get_conversation_history
        
        async with async_session() as session:
            # Get contact
            contact = await upsert_contact(session, phone_number=phone)
            name = contact.name or "Customer"
            
            # Get recent order/appointment count
            history = await get_conversation_history(session, phone, limit=20)
            order_count = sum(1 for h in history if h.direction == "outgoing" and "order" in h.content.lower())
            
            # Personalize template
            message = template.replace("{{phone}}", phone)
            message = message.replace("{{name}}", name)
            message = message.replace("{{orders}}", str(order_count))
            
            return message

    async def _update_campaign(self, campaign_id: int, **kwargs):
        async with async_session() as session:
            await session.execute(
                update(BroadcastCampaign)
                .where(BroadcastCampaign.id == campaign_id)
                .values(**kwargs)
            )
            await session.commit()


# Global broadcast engine instance (uses bridge URL from settings)
from config import settings as _settings

broadcast_engine = BroadcastEngine(
    bridge_url=_settings.whatsapp_bridge_url,
    rate_per_sec=float(_settings.broadcast_rate_per_sec),
)
