"""
Re-engagement Loop — nudges qualified-but-not-converted leads

Max 3 nudges per lead over 6 months. Stops if lead converts, opts out, or reaches max.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any

from sqlalchemy import select, update, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from db import Base, async_session
from config import settings
from logging_setup import get_logger

logger = get_logger("reengagement_loop")


# ---------------------------------------------------------------------------
# DB Model
# ---------------------------------------------------------------------------

class ReengagementLog(Base):
    __tablename__ = "reengagement_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    nudge_number: Mapped[int] = mapped_column(Integer, default=1)
    message_sent: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    response_received: Mapped[bool] = mapped_column(Boolean, default=False)
    converted: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Re-engagement Engine
# ---------------------------------------------------------------------------

class ReengagementLoop:
    """Re-engagement loop for qualified-but-not-converted leads."""

    MAX_NUDGES = 3
    WINDOW_DAYS = 180  # 6 months
    INACTIVITY_DAYS = 30

    NUDGE_MESSAGES = [
        "We noticed you haven't converted yet. Is there anything holding you back? We'd love to help!",
        "Still thinking it over? We have some new offers that might interest you. Want to hear more?",
        "This is our final nudge — we're here whenever you're ready. Just reply and we'll pick up right where we left off!",
    ]

    def __init__(self, message_sender=None):
        self.message_sender = message_sender

    async def scan_candidates(self, client_id: Optional[int] = None) -> List[Dict]:
        """Find leads with status=qualified or score >= 60, no appointment/conversion in last 30 days."""
        from db import Lead, Appointment
        from sqlalchemy import and_, or_

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.INACTIVITY_DAYS)
        candidates = []

        async with async_session() as session:
            query = select(Lead).where(
                and_(
                    Lead.status != "converted",
                    or_(Lead.status == "qualified", Lead.lead_score >= 60),
                    Lead.updated_at < cutoff,
                )
            )
            if client_id:
                query = query.where(Lead.client_id == client_id)

            result = await session.execute(query)
            leads = result.scalars().all()

            for lead in leads:
                recent_appt = await session.execute(
                    select(Appointment).where(
                        Appointment.phone_number == lead.phone_number,
                        Appointment.created_at > cutoff,
                    ).limit(1)
                )
                if recent_appt.scalar_one_or_none():
                    continue

                recent_nudge = await session.execute(
                    select(ReengagementLog).where(
                        ReengagementLog.lead_id == lead.id,
                        ReengagementLog.sent_at > cutoff,
                    ).order_by(ReengagementLog.sent_at.desc()).limit(1)
                )
                nudge = recent_nudge.scalar_one_or_none()
                if nudge and nudge.nudge_number >= self.MAX_NUDGES:
                    continue

                candidates.append({
                    "lead_id": lead.id,
                    "phone_number": lead.phone_number,
                    "client_id": lead.client_id,
                    "score": lead.lead_score,
                    "status": lead.status,
                    "name": lead.name,
                    "existing_nudges": nudge.nudge_number if nudge else 0,
                })

        logger.info(f"[v] Re-engagement scan: {len(candidates)} candidates found")
        return candidates

    async def send_nudge(self, lead_id: int) -> Dict:
        """Send personalized re-engagement message."""
        async with async_session() as session:
            from db import Lead
            lead = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()
            if not lead:
                return {"error": "Lead not found"}

            recent_nudge = await session.execute(
                select(ReengagementLog).where(
                    ReengagementLog.lead_id == lead_id,
                ).order_by(ReengagementLog.sent_at.desc()).limit(1)
            )
            nudge = recent_nudge.scalar_one_or_none()
            nudge_number = (nudge.nudge_number + 1) if nudge else 1
            if nudge_number > self.MAX_NUDGES:
                return {"error": "Max nudges reached"}

            window_start = datetime.now(timezone.utc) - timedelta(days=self.WINDOW_DAYS)
            recent_in_window = await session.execute(
                select(ReengagementLog).where(
                    ReengagementLog.lead_id == lead_id,
                    ReengagementLog.sent_at > window_start,
                )
            )
            if len(recent_in_window.scalars().all()) >= self.MAX_NUDGES:
                return {"error": "Max nudges reached within window"}

            msg_idx = min(nudge_number - 1, len(self.NUDGE_MESSAGES) - 1)
            message = self.NUDGE_MESSAGES[msg_idx]
            if lead.name:
                message = f"Hi {lead.name}, {message}"

            log_entry = ReengagementLog(
                lead_id=lead_id,
                phone_number=lead.phone_number,
                client_id=lead.client_id,
                nudge_number=nudge_number,
                message_sent=message,
            )
            session.add(log_entry)
            await session.commit()
            await session.refresh(log_entry)

        sent = await self._send(lead.phone_number, message)
        return {"status": "sent" if sent else "failed", "nudge_number": nudge_number, "log_id": log_entry.id}

    async def process(self) -> Dict[str, int]:
        """Called weekly — process re-engagement for all candidates."""
        stats = {"candidates_scanned": 0, "nudges_sent": 0, "skipped": 0, "errors": 0}

        try:
            candidates = await self.scan_candidates()
            stats["candidates_scanned"] = len(candidates)

            for candidate in candidates:
                try:
                    result = await self.send_nudge(candidate["lead_id"])
                    if result.get("status") == "sent":
                        stats["nudges_sent"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    logger.error(f"Re-engagement error for lead {candidate['lead_id']}: {e}")
                    stats["errors"] += 1

        except Exception as e:
            logger.error(f"Re-engagement loop error: {e}")
            stats["errors"] += 1

        logger.info(f"[v] Re-engagement processed: {stats}")
        return stats

    async def stop_nudges(self, lead_id: int, reason: str = "converted"):
        """Stop nudging a lead."""
        async with async_session() as session:
            result = await session.execute(
                select(ReengagementLog).where(
                    ReengagementLog.lead_id == lead_id,
                    ReengagementLog.converted == False,
                    ReengagementLog.opted_out == False,
                )
            )
            logs = result.scalars().all()
            for log in logs:
                if reason == "opted_out":
                    log.opted_out = True
                elif reason == "converted":
                    log.converted = True
                log.extra_metadata = {**(log.extra_metadata or {}), "stopped_reason": reason, "stopped_at": datetime.now(timezone.utc).isoformat()}
                await session.commit()
        logger.info(f"[v] Re-engagement stopped for lead {lead_id}: {reason}")

    async def _send(self, phone_number: str, message: str) -> bool:
        if not self.message_sender:
            logger.warning(f"No message sender configured, would re-engage {phone_number}: {message}")
            return True
        try:
            sent = await self.message_sender(phone_number, message)
            if sent:
                logger.info(f"[v] Re-engagement nudge sent to {phone_number}: {message[:50]}...")
            return sent
        except Exception as e:
            logger.error(f"Failed to send re-engagement nudge to {phone_number}: {e}")
            return False


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

reengagement_loop = ReengagementLoop()
