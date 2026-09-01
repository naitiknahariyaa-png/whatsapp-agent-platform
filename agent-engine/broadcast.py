"""
Broadcasting Engine — async queue-based bulk messaging.
Sends via the WhatsApp bridge HTTP /send endpoint.
No Redis/BullMQ dependency — uses asyncio.Queue + SQLite for persistence.
"""
import asyncio
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, func, delete
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, Integer, DateTime, JSON

from db import Base, async_session

logger = logging.getLogger("broadcast")


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
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | paused | cancelled | completed | failed
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[Optional[list]] = mapped_column(JSON, default=list)  # per-phone status (legacy)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Bulk-import lists + per-send audit rows (v2 — owner-scoped)
# ---------------------------------------------------------------------------

class ContactList(Base):
    """A named, reusable list of phone numbers belonging to one owner."""
    __tablename__ = "contact_lists"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    list_name: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ContactListMember(Base):
    """One phone number inside a contact list (deduped per list)."""
    __tablename__ = "contact_list_members"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(Integer, index=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(40))  # csv | paste | manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class CampaignSend(Base):
    """One row per (campaign, recipient) send attempt — audit trail + resume."""
    __tablename__ = "campaign_sends"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | sent | failed | skipped
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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

    async def send_campaign(self, list_name: str, message_template: str, client_id: int = 1) -> dict:
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
        task = asyncio.create_task(self._run_campaign(campaign_id, phones, message_template, client_id=client_id))
        self._running_tasks[campaign_id] = task
        return {"campaign_id": campaign_id, "total": len(phones), "status": "started"}

    async def _run_campaign_v2(self, campaign_id: int, owner_id: int,
                               client_id: int, template: str):
        """Sequential sender — routes every message through the anti-ban
        outbound pipeline (opt-out re-check, caps, cooldown, randomized delay).
        Supports pause / cancel / resume via the campaign status flag and
        writes one campaign_sends row per attempt (audit trail)."""
        from outbound_limiter import send_whatsapp, is_opted_out

        async def _publish(payload: dict):
            try:
                from event_bus import get_event_bus
                await get_event_bus().publish_dict(
                    "campaign.send_progress", owner_id, payload)
            except Exception as e:  # event bus must never break a send
                logger.debug("event publish failed: %s", e)

        # Mark running — but never clobber a pause/cancel that landed first
        async with async_session() as session:
            c0 = (await session.execute(
                select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
            )).scalar_one_or_none()
            if c0 and c0.status == "pending":
                c0.status = "running"
                await session.commit()
            elif c0 and c0.status in ("paused", "cancelled"):
                return  # paused/cancelled before the worker even started
        sent = failed = skipped = 0

        while True:
            # Fetch next pending recipient (doubles as the resume checkpoint)
            async with async_session() as session:
                c = (await session.execute(
                    select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
                )).scalar_one_or_none()
                if not c or c.status == "cancelled":
                    self._running_tasks.pop(campaign_id, None)
                    break
                if c.status == "paused":
                    self._running_tasks.pop(campaign_id, None)
                    return  # resume_campaign re-spawns this worker
                row = (await session.execute(
                    select(CampaignSend).where(
                        CampaignSend.campaign_id == campaign_id,
                        CampaignSend.status == "pending")
                    .order_by(CampaignSend.id).limit(1)
                )).scalar_one_or_none()
                if not row:
                    break
                row.status = "sending"
                await session.commit()
                phone = row.phone

            # Safety rail: re-check opt-out immediately before EVERY send
            if is_opted_out(phone):
                await self._mark_send(campaign_id, phone, "skipped", "opted out")
                skipped += 1
                await _publish({"campaign_id": campaign_id, "phone": phone,
                                "status": "skipped", "sent": sent,
                                "failed": failed, "skipped": skipped})
                continue

            personalized = await self._personalize_message(phone, template, client_id=client_id)
            ok = await send_whatsapp(phone, personalized, client_id=client_id)
            await self._mark_send(campaign_id, phone, "sent" if ok else "failed",
                                  None if ok else "bridge send failed")

            if ok:
                sent += 1
            else:
                failed += 1
            await self._update_campaign(campaign_id, sent=sent, failed=failed)
            await _publish({"campaign_id": campaign_id, "phone": phone,
                            "status": "sent" if ok else "failed", "sent": sent,
                            "failed": failed, "skipped": skipped})

        async with async_session() as session:
            c = (await session.execute(
                select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
            )).scalar_one_or_none()
            if c and c.status not in ("cancelled", "paused"):
                c.status = "completed"
                c.completed_at = datetime.now(timezone.utc)
                await session.commit()
        self._running_tasks.pop(campaign_id, None)

    async def _mark_send(self, campaign_id: int, phone: str,
                         status: str, error: Optional[str]):
        async with async_session() as session:
            row = (await session.execute(
                select(CampaignSend).where(
                    CampaignSend.campaign_id == campaign_id,
                    CampaignSend.phone == phone,
                    CampaignSend.status == "sending")
                .order_by(CampaignSend.id.desc()).limit(1)
            )).scalar_one_or_none()
            if row:
                row.status = status
                row.error = error
                row.timestamp = datetime.now(timezone.utc)
                await session.commit()

    async def pause_campaign(self, campaign_id: int) -> dict:
        await self._update_campaign(campaign_id, status="paused")
        return {"campaign_id": campaign_id, "status": "paused"}

    async def resume_campaign(self, campaign_id: int) -> dict:
        """Pick up exactly where the campaign left off: only recipients whose
        campaign_sends row is still pending are re-enqueued; already-sent
        numbers can never be double-messaged."""
        async with async_session() as session:
            c = (await session.execute(
                select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
            )).scalar_one_or_none()
            if not c:
                return {"error": "Campaign not found"}
            if c.status not in ("paused", "failed"):
                return {"error": f"Campaign is '{c.status}'; can only resume paused/failed"}
            pending = (await session.execute(
                select(func.count(CampaignSend.id)).where(
                    CampaignSend.campaign_id == campaign_id,
                    CampaignSend.status == "pending")
            )).scalar() or 0
            cl = (await session.execute(
                select(ContactList).where(ContactList.list_name == c.list_name)
            )).scalar_one_or_none()
            owner_id = cl.owner_id if cl else 1
            template = c.message_template

        if campaign_id in self._running_tasks:
            return {"campaign_id": campaign_id, "status": "already running"}
        # Reset to pending so the re-spawned worker's start-guard passes
        await self._update_campaign(campaign_id, status="pending")
        task = asyncio.create_task(self._run_campaign_v2(
            campaign_id, owner_id, owner_id, template))
        self._running_tasks[campaign_id] = task
        return {"campaign_id": campaign_id, "status": "resumed", "remaining": pending}

    async def cancel_campaign(self, campaign_id: int) -> dict:
        await self._update_campaign(campaign_id, status="cancelled")
        return {"campaign_id": campaign_id, "status": "cancelled"}

    async def campaign_stats(self, campaign_id: int) -> Optional[dict]:
        """Live stats from campaign_sends + reply-rate from inbound messages."""
        async with async_session() as session:
            c = (await session.execute(
                select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
            )).scalar_one_or_none()
            if not c:
                return None
            counts = {"sent": 0, "failed": 0, "skipped": 0, "pending": 0,
                      "sending": 0}
            for st, n in (await session.execute(
                select(CampaignSend.status, func.count(CampaignSend.id))
                .where(CampaignSend.campaign_id == campaign_id)
                .group_by(CampaignSend.status)
            )).all():
                counts[st] = n
            replies = 0
            try:
                from db import Message
                phones = (await session.execute(
                    select(CampaignSend.phone)
                    .where(CampaignSend.campaign_id == campaign_id,
                           CampaignSend.status == "sent")
                )).scalars().all()
                if phones:
                    replies = (await session.execute(
                        select(func.count(Message.id)).where(
                            Message.direction == "incoming",
                            Message.created_at >= c.created_at,
                            Message.phone_number.in_(phones))
                    )).scalar() or 0
            except Exception as e:
                logger.debug("reply count failed: %s", e)
            sent_total = counts["sent"]
            remaining = counts["pending"]
            return {
                "campaign_id": campaign_id, "list_name": c.list_name,
                "status": c.status, "total": c.total,
                "sent": sent_total, "failed": counts["failed"],
                "skipped": counts["skipped"], "pending": remaining,
                "replies": replies,
                "reply_rate_pct": round(100 * replies / sent_total, 1) if sent_total else 0.0,
                "est_minutes_remaining": round(remaining * 12.5 / 60, 1),
                "created_at": c.created_at.isoformat(),
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }

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

    # -- Bulk import (v2, owner-scoped) ---------------------------------------

    async def import_numbers(self, owner_id: int, list_name: str,
                             entries: List[tuple], source: str = "csv") -> dict:
        """Import (phone, name) entries into a named contact list.

        Pipeline: normalize -> validate -> in-list dedup -> opt-out check ->
        existing-customer dedup (owner's contacts table). Nothing is silently
        dropped — every skip is counted and reported.
        """
        from outbound_limiter import is_opted_out, normalize_phone_number
        from db import Contact, hmac_phone_hash

        invalid: List[dict] = []
        opted_out: List[str] = []
        seen: set = set()
        clean: List[tuple] = []
        dup_in_list = 0
        existing_customers: List[str] = []

        for raw, nm in entries:
            phone = normalize_phone_number(raw or "")
            digits = sum(ch.isdigit() for ch in (phone or ""))
            if not phone or digits < 10:
                invalid.append({"raw": raw, "reason": "malformed (needs >=10 digits)"})
                continue
            if phone in seen:
                dup_in_list += 1
                continue
            if is_opted_out(phone):
                opted_out.append(phone)
                continue
            seen.add(phone)
            clean.append((phone, (nm or "").strip()))

        async with async_session() as session:
            cl = (await session.execute(
                select(ContactList).where(ContactList.owner_id == owner_id,
                                          ContactList.list_name == list_name)
            )).scalar_one_or_none()
            if not cl:
                cl = ContactList(owner_id=owner_id, list_name=list_name,
                                 description=f"imported via {source}")
                session.add(cl)
                await session.flush()
            else:
                cl.updated_at = datetime.now(timezone.utc)

            existing_phones = set((await session.execute(
                select(ContactListMember.phone)
                .where(ContactListMember.list_id == cl.id)
            )).scalars().all())

            existing_cust_set = set()
            if clean:
                hashes = [hmac_phone_hash(p) for p, _ in clean]
                rows = (await session.execute(
                    select(Contact.phone_hash).where(
                        Contact.client_id == owner_id,
                        Contact.phone_hash.in_(hashes))
                )).scalars().all()
                existing_cust_set = set(rows)

            added = 0
            for phone, nm in clean:
                if phone in existing_phones:
                    dup_in_list += 1
                    continue
                if hmac_phone_hash(phone) in existing_cust_set:
                    existing_customers.append(phone)
                    continue
                session.add(ContactListMember(
                    list_id=cl.id, phone=phone, name=nm or None, source=source))
                added += 1
            await session.commit()
            total = (await session.execute(
                select(func.count(ContactListMember.id))
                .where(ContactListMember.list_id == cl.id)
            )).scalar() or 0

        # Write invalid numbers for inspection (never silently dropped)
        if invalid:
            try:
                with open("invalid_numbers.txt", "a", encoding="utf-8") as f:
                    for item in invalid:
                        f.write(f"{item.get('raw')}\t{item.get('reason')}\n")
            except OSError:
                pass

        return {
            "list_name": list_name, "list_id": cl.id,
            "imported": added, "list_total": total,
            "invalid": len(invalid), "invalid_file": "invalid_numbers.txt" if invalid else None,
            "duplicates_in_list": dup_in_list,
            "already_customers": len(existing_customers),
            "opted_out_excluded": opted_out,
        }

    async def get_contact_list(self, owner_id: int, list_name: str) -> Optional[dict]:
        """List contents + stats (for review before sending)."""
        async with async_session() as session:
            cl = (await session.execute(
                select(ContactList).where(ContactList.owner_id == owner_id,
                                          ContactList.list_name == list_name)
            )).scalar_one_or_none()
            if not cl:
                return None
            members = (await session.execute(
                select(ContactListMember)
                .where(ContactListMember.list_id == cl.id)
                .order_by(ContactListMember.id)
            )).scalars().all()
            return {
                "list_id": cl.id, "list_name": cl.list_name,
                "owner_id": cl.owner_id, "created_at": cl.created_at.isoformat(),
                "total": len(members),
                "members": [{"phone": m.phone, "name": m.name, "source": m.source}
                            for m in members[:200]],
            }

    async def get_owner_lists(self, owner_id: int) -> List[dict]:
        async with async_session() as session:
            rows = (await session.execute(
                select(ContactList).where(ContactList.owner_id == owner_id)
            )).scalars().all()
            out = []
            for cl in rows:
                count = (await session.execute(
                    select(func.count(ContactListMember.id))
                    .where(ContactListMember.list_id == cl.id)
                )).scalar() or 0
                out.append({"list_id": cl.id, "list_name": cl.list_name,
                            "total": count, "created_at": cl.created_at.isoformat()})
            return out

    # -- Campaign launch with safety rails (v2) -------------------------------

    async def launch_campaign(self, owner_id: int, list_name: str,
                              message_template: str, client_id: Optional[int] = None,
                              force: bool = False,
                              ignore_quiet_hours: bool = False) -> dict:
        """Create a campaign against a contact list and enqueue each recipient
        onto the EXISTING anti-ban outbound pipeline (one sender, one set of rules)."""
        import os
        members: List[ContactListMember] = []
        async with async_session() as session:
            cl = (await session.execute(
                select(ContactList).where(ContactList.owner_id == owner_id,
                                          ContactList.list_name == list_name)
            )).scalar_one_or_none()
            if not cl:
                return {"error": f"List '{list_name}' not found. Import it first."}
            members = (await session.execute(
                select(ContactListMember)
                .where(ContactListMember.list_id == cl.id)
            )).scalars().all()

        if not members:
            return {"error": "List is empty"}

        # Safety rail 1: hard confirmation above threshold
        threshold = int(os.getenv("BROADCAST_CONFIRM_THRESHOLD", "500"))
        if len(members) > threshold and not force:
            return {"needs_force": True, "count": len(members),
                    "message": (f"List '{list_name}' has {len(members)} recipients "
                                f"(> {threshold}). Re-run with --force to confirm.")}

        # Safety rail 2: quiet hours (unless explicitly overridden)
        if not ignore_quiet_hours:
            qs = os.getenv("BROADCAST_QUIET_START", "")
            qe = os.getenv("BROADCAST_QUIET_END", "")
            if qs and qe:
                from datetime import datetime as _dt
                now = _dt.now().time()
                start = _dt.strptime(qs, "%H:%M").time()
                end = _dt.strptime(qe, "%H:%M").time()
                in_quiet = (start <= now <= end) if start <= end else (now >= start or now <= end)
                if in_quiet:
                    return {"error": (f"Quiet hours active ({qs}-{qe}). Use "
                                      "--ignore-quiet-hours only for time-sensitive sends.")}

        cid = client_id if client_id is not None else owner_id
        async with async_session() as session:
            campaign = BroadcastCampaign(
                list_name=list_name, message_template=message_template,
                status="pending", total=len(members))
            session.add(campaign)
            await session.flush()
            campaign_id = campaign.id
            for m in members:
                session.add(CampaignSend(campaign_id=campaign_id, phone=m.phone,
                                         status="pending"))
            await session.commit()

        task = asyncio.create_task(self._run_campaign_v2(
            campaign_id, owner_id, cid, message_template))
        self._running_tasks[campaign_id] = task
        return {"campaign_id": campaign_id, "total": len(members),
                "list_name": list_name, "status": "started"}

    # -- Internal worker ----------------------------------------------------

    async def _run_campaign(self, campaign_id: int, phones: List[str], template: str, client_id: int = 1):
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
                    personalized = await self._personalize_message(phone, template, client_id=client_id)
                    
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

    async def _personalize_message(self, phone: str, template: str, client_id: int = 1) -> str:
        """Personalize message with customer name and order history"""
        from db import upsert_contact, get_conversation_history
        
        async with async_session() as session:
            # Get contact
            contact = await upsert_contact(session, phone_number=phone, client_id=client_id)
            name = contact.name or "Customer"
            
            # Get recent order/appointment count
            history = await get_conversation_history(session, phone, limit=20, client_id=client_id)
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
