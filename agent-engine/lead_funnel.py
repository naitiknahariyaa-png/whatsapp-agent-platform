"""
Lead Qualification Funnel — Reply-Interrupt + Opt-Out Automation

Stages: new → welcome_sent → reminder_1_sent → last_attempt_sent → cold
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass, field

from sqlalchemy import select, update, delete, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from db import Base, async_session
from config import settings
from logging_setup import get_logger

logger = get_logger("lead_funnel")


# ---------------------------------------------------------------------------
# DB Model
# ---------------------------------------------------------------------------

class LeadFunnelEnrollment(Base):
    __tablename__ = "lead_funnel_enrollments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    stage: Mapped[str] = mapped_column(String(30), default="new", index=True)
    trigger_event: Mapped[Optional[str]] = mapped_column(String(100))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_action_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    welcome_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_1_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_attempt_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Funnel Engine
# ---------------------------------------------------------------------------

class FunnelStage(Enum):
    NEW = "new"
    WELCOME_SENT = "welcome_sent"
    REMINDER_1_SENT = "reminder_1_sent"
    LAST_ATTEMPT_SENT = "last_attempt_sent"
    COLD = "cold"


class LeadFunnel:
    """Lead qualification funnel with reply-interrupt and opt-out support."""

    WELCOME_DELAY_HOURS = 24
    REMINDER_1_DELAY_HOURS = 48
    LAST_ATTEMPT_DELAY_HOURS = 48

    OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "बंद", "रद्द", "opt out", "end"}

    def __init__(self, message_sender=None):
        self.message_sender = message_sender
        self._running = False

    async def enroll(self, phone_number: str, client_id: int, trigger_event: str,
                     metadata: Optional[Dict] = None) -> Optional[LeadFunnelEnrollment]:
        """Enroll a new lead in the funnel."""
        async with async_session() as session:
            existing = await session.execute(
                select(LeadFunnelEnrollment).where(
                    LeadFunnelEnrollment.phone_number == phone_number,
                    LeadFunnelEnrollment.client_id == client_id,
                    LeadFunnelEnrollment.is_active == True,
                )
            )
            enrollment = existing.scalar_one_or_none()
            if enrollment:
                logger.info(f"Lead {phone_number} already enrolled in funnel, updating trigger")
                enrollment.trigger_event = trigger_event
                enrollment.extra_metadata = metadata or enrollment.extra_metadata or {}
                enrollment.updated_at = datetime.now(timezone.utc)
            else:
                enrollment = LeadFunnelEnrollment(
                    phone_number=phone_number,
                    client_id=client_id,
                    stage=FunnelStage.NEW.value,
                    trigger_event=trigger_event,
                    extra_metadata=metadata or {},
                )
                session.add(enrollment)
            await session.commit()
            await session.refresh(enrollment)
            logger.info(f"[v] Enrolled {phone_number} in lead funnel (trigger={trigger_event})")
            return enrollment

    async def on_lead_reply(self, phone_number: str, client_id: int) -> bool:
        """Interrupt funnel for this lead — mark all active enrollments inactive."""
        async with async_session() as session:
            result = await session.execute(
                select(LeadFunnelEnrollment).where(
                    LeadFunnelEnrollment.phone_number == phone_number,
                    LeadFunnelEnrollment.client_id == client_id,
                    LeadFunnelEnrollment.is_active == True,
                )
            )
            enrollments = result.scalars().all()
            if not enrollments:
                return False

            for enrollment in enrollments:
                enrollment.is_active = False
                enrollment.updated_at = datetime.now(timezone.utc)
                enrollment.extra_metadata = {**(enrollment.extra_metadata or {}), "interrupted_at": datetime.now(timezone.utc).isoformat(), "reason": "lead_replied"}
            await session.commit()
            logger.info(f"[v] Funnel interrupted for {phone_number} ({len(enrollments)} enrollment(s) deactivated)")
            return True

    def is_opt_out_message(self, text: str) -> bool:
        """Return True if the message text matches an opt-out keyword."""
        if not text:
            return False
        normalized = text.strip().lower()
        return normalized in self.OPT_OUT_KEYWORDS

    async def on_opt_out(self, phone_number: str, client_id: int) -> bool:
        """Set opt-out flag (persisted) and remove from all campaigns/funnels."""
        from services.compliance import compliance_manager

        # In-memory opt-out record (used by check_can_send at runtime)
        compliance_manager.record_opt_out(phone_number, client_id, source="funnel_opt_out")

        # Persist opt-out as a denied marketing consent so it survives restarts
        try:
            from compliance_loop import compliance_loop
            await compliance_loop.record_consent(
                phone_number, client_id, consent_type="marketing",
                granted=False, source="funnel_opt_out",
            )
        except Exception as e:
            logger.warning(f"Persisted opt-out consent write failed for {phone_number}: {e}")

        # Feed the unsubscribe signal into lead scoring
        try:
            from services.lead_scoring import scoring_engine, LeadSignal
            scoring_engine.record_signal(phone_number, LeadSignal.UNSUBSCRIBE, client_id=client_id)
        except Exception as e:
            logger.warning(f"Lead score opt-out signal failed for {phone_number}: {e}")

        await self.on_lead_reply(phone_number, client_id)

        from drip_campaigns import engine as drip_engine
        try:
            for key in list(drip_engine.enrollments.keys()):
                enrollment = drip_engine.enrollments[key]
                if enrollment.contact_id == phone_number:
                    await drip_engine.unenroll(enrollment.campaign_id, phone_number)
        except Exception as e:
            logger.warning(f"Drip campaign unenroll error for {phone_number}: {e}")

        async with async_session() as session:
            from db import Contact
            contact = (await session.execute(
                select(Contact).where(Contact.phone_number == phone_number, Contact.client_id == client_id)
            )).scalar_one_or_none()
            if contact:
                contact.tags = list(set((contact.tags or []) + ["opt_out"]))
                await session.commit()

        logger.info(f"[v] Opt-out processed for {phone_number} (client={client_id})")
        return True

    async def process_funnel(self) -> Dict[str, int]:
        """Process all active funnel enrollments. Called periodically via ARQ."""
        now = datetime.now(timezone.utc)
        stats = {"processed": 0, "welcome_sent": 0, "reminder_1_sent": 0, "last_attempt_sent": 0, "cold": 0, "errors": 0}

        try:
            async with async_session() as session:
                result = await session.execute(
                    select(LeadFunnelEnrollment).where(
                        LeadFunnelEnrollment.is_active == True,
                    )
                )
                enrollments = result.scalars().all()

            for enrollment in enrollments:
                try:
                    stage_stats = await self._process_enrollment(enrollment, now)
                    stats["processed"] += 1
                    for k, v in stage_stats.items():
                        stats[k] = stats.get(k, 0) + v
                except Exception as e:
                    logger.error(f"Error processing funnel enrollment {enrollment.id}: {e}")
                    stats["errors"] += 1

        except Exception as e:
            logger.error(f"Funnel processing error: {e}")
            stats["errors"] += 1

        logger.info(f"[v] Funnel processed: {stats}")
        return stats

    async def _process_enrollment(self, enrollment: LeadFunnelEnrollment, now: datetime) -> Dict[str, int]:
        """Process a single enrollment based on its stage and timing. Returns stats dict."""
        from services.compliance import compliance_manager
        stage_stats = {}

        if not compliance_manager.check_can_send(enrollment.phone_number, enrollment.client_id):
            enrollment.is_active = False
            enrollment.extra_metadata = {**(enrollment.extra_metadata or {}), "blocked_at": now.isoformat(), "reason": "opted_out"}
            async with async_session() as session:
                session.add(enrollment)
                await session.commit()
            return stage_stats

        stage = enrollment.stage
        last_action = enrollment.last_action_at
        if last_action.tzinfo is None:
            last_action = last_action.replace(tzinfo=timezone.utc)
        elapsed = (now - last_action).total_seconds() / 3600

        if stage == FunnelStage.NEW.value:
            if elapsed >= self.WELCOME_DELAY_HOURS:
                if await self._send_welcome(enrollment):
                    enrollment.stage = FunnelStage.WELCOME_SENT.value
                    enrollment.welcome_sent_at = now
                    enrollment.last_action_at = now
                    stage_stats["welcome_sent"] = 1
                    async with async_session() as session:
                        session.add(enrollment)
                        await session.commit()

        elif stage == FunnelStage.WELCOME_SENT.value:
            welcome_time = enrollment.welcome_sent_at
            if welcome_time:
                if welcome_time.tzinfo is None:
                    welcome_time = welcome_time.replace(tzinfo=timezone.utc)
                since_welcome = (now - welcome_time).total_seconds() / 3600
            else:
                since_welcome = 999
            if since_welcome >= self.REMINDER_1_DELAY_HOURS:
                if await self._send_reminder_1(enrollment):
                    enrollment.stage = FunnelStage.REMINDER_1_SENT.value
                    enrollment.reminder_1_sent_at = now
                    enrollment.last_action_at = now
                    stage_stats["reminder_1_sent"] = 1
                    async with async_session() as session:
                        session.add(enrollment)
                        await session.commit()

        elif stage == FunnelStage.REMINDER_1_SENT.value:
            r1_time = enrollment.reminder_1_sent_at
            if r1_time:
                if r1_time.tzinfo is None:
                    r1_time = r1_time.replace(tzinfo=timezone.utc)
                since_r1 = (now - r1_time).total_seconds() / 3600
            else:
                since_r1 = 999
            if since_r1 >= self.LAST_ATTEMPT_DELAY_HOURS:
                if await self._send_last_attempt(enrollment):
                    enrollment.stage = FunnelStage.COLD.value
                    enrollment.last_attempt_sent_at = now
                    enrollment.is_active = False
                    enrollment.last_action_at = now
                    enrollment.extra_metadata = {**(enrollment.extra_metadata or {}), "cold_at": now.isoformat()}
                    stage_stats["last_attempt_sent"] = 1
                    stage_stats["cold"] = 1
                    async with async_session() as session:
                        session.add(enrollment)
                        await session.commit()

        return stage_stats

    async def _send_welcome(self, enrollment: LeadFunnelEnrollment) -> bool:
        message = f"Welcome! Thanks for reaching out. How can we help you today?"
        return await self._send(enrollment, message)

    async def _send_reminder_1(self, enrollment: LeadFunnelEnrollment) -> bool:
        message = f"Just checking in — are you still interested? We'd love to help!"
        return await self._send(enrollment, message)

    async def _send_last_attempt(self, enrollment: LeadFunnelEnrollment) -> bool:
        message = f"This is our last attempt to reach you. Feel free to message us anytime in the future!"
        return await self._send(enrollment, message)

    async def _send(self, enrollment: LeadFunnelEnrollment, message: str) -> bool:
        if not self.message_sender:
            logger.warning(f"No message sender configured, would send to {enrollment.phone_number}: {message}")
            return True
        try:
            sent = await self.message_sender(enrollment.phone_number, message)
            if sent:
                logger.info(f"[v] Funnel message sent to {enrollment.phone_number}: {message[:50]}...")
            return sent
        except Exception as e:
            logger.error(f"Failed to send funnel message to {enrollment.phone_number}: {e}")
            return False

    async def get_active_enrollments(self, client_id: Optional[int] = None) -> List[Dict]:
        """Get active funnel enrollments, optionally filtered by client."""
        async with async_session() as session:
            query = select(LeadFunnelEnrollment).where(LeadFunnelEnrollment.is_active == True)
            if client_id:
                query = query.where(LeadFunnelEnrollment.client_id == client_id)
            result = await session.execute(query)
            enrollments = result.scalars().all()
            return [
                {
                    "id": e.id,
                    "phone_number": e.phone_number,
                    "client_id": e.client_id,
                    "stage": e.stage,
                    "trigger_event": e.trigger_event,
                    "enrolled_at": e.enrolled_at.isoformat() if e.enrolled_at else None,
                    "last_action_at": e.last_action_at.isoformat() if e.last_action_at else None,
                }
                for e in enrollments
            ]


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

lead_funnel = LeadFunnel()
