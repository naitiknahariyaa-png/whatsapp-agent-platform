"""
Appointment Nurture Loop — automated reminders, no-show detection, feedback requests

Stages: booked → confirmation_sent → reminder_24h_sent → reminder_1h_sent → feedback_requested → completed
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass, field

from sqlalchemy import select, update, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from db import Base, async_session
from config import settings
from logging_setup import get_logger

logger = get_logger("appointment_nurture")


# ---------------------------------------------------------------------------
# DB Model
# ---------------------------------------------------------------------------

class AppointmentNurtureEnrollment(Base):
    __tablename__ = "appointment_nurture_enrollments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(Integer, index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    stage: Mapped[str] = mapped_column(String(30), default="booked", index=True)
    confirmation_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_24h_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reminder_1h_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    feedback_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    no_show_detected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    feedback_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Nurture Engine
# ---------------------------------------------------------------------------

class NurtureStage(Enum):
    BOOKED = "booked"
    CONFIRMATION_SENT = "confirmation_sent"
    REMINDER_24H_SENT = "reminder_24h_sent"
    REMINDER_1H_SENT = "reminder_1h_sent"
    FEEDBACK_REQUESTED = "feedback_requested"
    COMPLETED = "completed"


class AppointmentNurture:
    """Appointment nurture loop with reminders, no-show detection, and feedback."""

    def __init__(self, message_sender=None):
        self.message_sender = message_sender

    async def enroll(self, appointment_id: int) -> Optional[AppointmentNurtureEnrollment]:
        """Enroll an appointment in the nurture loop."""
        from db import Appointment as AppointmentModel
        async with async_session() as session:
            appointment = (await session.execute(
                select(AppointmentModel).where(AppointmentModel.id == appointment_id)
            )).scalar_one_or_none()
            if not appointment:
                logger.warning(f"Appointment {appointment_id} not found")
                return None

            existing = await session.execute(
                select(AppointmentNurtureEnrollment).where(
                    AppointmentNurtureEnrollment.appointment_id == appointment_id,
                    AppointmentNurtureEnrollment.is_active == True,
                )
            )
            enrollment = existing.scalar_one_or_none()
            if enrollment:
                logger.info(f"Appointment {appointment_id} already in nurture loop")
                return enrollment

            enrollment = AppointmentNurtureEnrollment(
                appointment_id=appointment_id,
                client_id=appointment.client_id,
                phone_number=appointment.phone_number,
                stage=NurtureStage.BOOKED.value,
            )
            session.add(enrollment)
            await session.commit()
            await session.refresh(enrollment)
            logger.info(f"[v] Enrolled appointment {appointment_id} in nurture loop")
            return enrollment

    async def process_nurture(self) -> Dict[str, int]:
        """Process all active nurture enrollments. Called periodically via ARQ."""
        now = datetime.now(timezone.utc)
        stats = {"processed": 0, "confirmations_sent": 0, "reminders_24h_sent": 0, "reminders_1h_sent": 0, "feedback_sent": 0, "no_shows_detected": 0, "errors": 0}

        try:
            async with async_session() as session:
                result = await session.execute(
                    select(AppointmentNurtureEnrollment).where(
                        AppointmentNurtureEnrollment.is_active == True,
                    )
                )
                enrollments = result.scalars().all()

            for enrollment in enrollments:
                try:
                    enrollment_stats = await self._process_enrollment(enrollment, now)
                    stats["processed"] += 1
                    for k, v in enrollment_stats.items():
                        stats[k] = stats.get(k, 0) + v
                except Exception as e:
                    logger.error(f"Error processing nurture enrollment {enrollment.id}: {e}")
                    stats["errors"] += 1

        except Exception as e:
            logger.error(f"Nurture processing error: {e}")
            stats["errors"] += 1

        logger.info(f"[v] Nurture processed: {stats}")
        return stats

    async def _process_enrollment(self, enrollment: AppointmentNurtureEnrollment, now: datetime) -> Dict[str, int]:
        """Process a single enrollment based on appointment timing."""
        enrollment_stats: Dict[str, int] = {}
        from db import Appointment

        async with async_session() as session:
            # Re-attach the enrollment to this session (it was loaded in the caller's session)
            enrollment = (await session.execute(
                select(AppointmentNurtureEnrollment).where(
                    AppointmentNurtureEnrollment.id == enrollment.id
                )
            )).scalar_one_or_none()
            if not enrollment:
                return enrollment_stats

            appointment = (await session.execute(
                select(Appointment).where(Appointment.id == enrollment.appointment_id)
            )).scalar_one_or_none()
            if not appointment:
                enrollment.is_active = False
                await session.commit()
                return enrollment_stats

            if appointment.status in ("cancelled", "completed", "no_show"):
                enrollment.is_active = False
                enrollment.stage = NurtureStage.COMPLETED.value
                await session.commit()
                return enrollment_stats

            appt_datetime = self._parse_appointment_datetime(appointment.appointment_date, appointment.appointment_time)
            if not appt_datetime:
                return enrollment_stats

            stage = enrollment.stage
            now_utc = now

            if stage == NurtureStage.BOOKED.value:
                if await self._send_confirmation(enrollment, appointment):
                    enrollment.stage = NurtureStage.CONFIRMATION_SENT.value
                    enrollment.confirmation_sent_at = now_utc
                    enrollment_stats["confirmations_sent"] = 1
                    await session.commit()

            elif stage == NurtureStage.CONFIRMATION_SENT.value:
                t_24h = appt_datetime - timedelta(hours=24)
                t_1h = appt_datetime - timedelta(hours=1)
                if now_utc >= t_24h and enrollment.reminder_24h_sent_at is None:
                    if await self._send_reminder_24h(enrollment, appointment):
                        enrollment.stage = NurtureStage.REMINDER_24H_SENT.value
                        enrollment.reminder_24h_sent_at = now_utc
                        enrollment_stats["reminders_24h_sent"] = 1
                        await session.commit()

            elif stage == NurtureStage.REMINDER_24H_SENT.value:
                t_1h = appt_datetime - timedelta(hours=1)
                if now_utc >= t_1h and enrollment.reminder_1h_sent_at is None:
                    if await self._send_reminder_1h(enrollment, appointment):
                        enrollment.stage = NurtureStage.REMINDER_1H_SENT.value
                        enrollment.reminder_1h_sent_at = now_utc
                        enrollment_stats["reminders_1h_sent"] = 1
                        await session.commit()

            elif stage == NurtureStage.REMINDER_1H_SENT.value:
                t_after = appt_datetime + timedelta(hours=1)
                if now_utc >= t_after and enrollment.feedback_sent_at is None:
                    if await self._send_feedback(enrollment, appointment):
                        enrollment.stage = NurtureStage.FEEDBACK_REQUESTED.value
                        enrollment.feedback_sent_at = now_utc
                        enrollment_stats["feedback_sent"] = 1
                        await session.commit()

            t_no_show = appt_datetime + timedelta(hours=2)
            if now_utc >= t_no_show and appointment.status == "scheduled" and enrollment.no_show_detected_at is None:
                appointment.status = "no_show"
                enrollment.no_show_detected_at = now_utc
                enrollment.extra_metadata = {**(enrollment.extra_metadata or {}), "no_show": True}
                await self._send_no_show_rebooking(enrollment, appointment)
                enrollment_stats["no_shows_detected"] = 1
                await session.commit()

        return enrollment_stats

    def _parse_appointment_datetime(self, date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
        if not date_str or not time_str:
            return None
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    async def _send_confirmation(self, enrollment: AppointmentNurtureEnrollment, appointment) -> bool:
        title = appointment.title or "your appointment"
        message = f"Your appointment '{title}' is confirmed for {appointment.appointment_date} at {appointment.appointment_time}."
        return await self._send(enrollment, message)

    async def _send_reminder_24h(self, enrollment: AppointmentNurtureEnrollment, appointment) -> bool:
        title = appointment.title or "your appointment"
        message = f"Reminder: '{title}' is tomorrow at {appointment.appointment_time}. See you then!"
        return await self._send(enrollment, message)

    async def _send_reminder_1h(self, enrollment: AppointmentNurtureEnrollment, appointment) -> bool:
        title = appointment.title or "your appointment"
        message = f"Reminder: '{title}' starts in 1 hour at {appointment.appointment_time}. We're ready for you!"
        return await self._send(enrollment, message)

    async def _send_feedback(self, enrollment: AppointmentNurtureEnrollment, appointment) -> bool:
        title = appointment.title or "your appointment"
        message = f"How was '{title}'? Reply with a rating 1-5 or share your feedback!"
        return await self._send(enrollment, message)

    async def _send_no_show_rebooking(self, enrollment: AppointmentNurtureEnrollment, appointment) -> bool:
        title = appointment.title or "your appointment"
        message = f"We missed you for '{title}'. Would you like to reschedule? Reply YES to book a new time."
        return await self._send(enrollment, message)

    async def record_feedback(self, enrollment_id: int, score: int) -> Dict:
        """Record feedback score and update lead score."""
        async with async_session() as session:
            enrollment = (await session.execute(
                select(AppointmentNurtureEnrollment).where(AppointmentNurtureEnrollment.id == enrollment_id)
            )).scalar_one_or_none()
            if not enrollment:
                return {"error": "Enrollment not found"}

            enrollment.feedback_score = score
            enrollment.stage = NurtureStage.COMPLETED.value
            enrollment.is_active = False
            enrollment.extra_metadata = {**(enrollment.extra_metadata or {}), "feedback_score": score, "feedback_at": datetime.now(timezone.utc).isoformat()}
            await session.commit()

        score_delta = 10 if score >= 4 else (-15 if score <= 2 else 0)
        if score_delta != 0:
            try:
                from services.lead_scoring import scoring_engine
                scoring_engine.record_signal(
                    enrollment.phone_number,
                    __import__("services.lead_scoring", fromlist=["LeadSignal"]).LeadSignal.POSITIVE_FEEDBACK if score_delta > 0 else __import__("services.lead_scoring", fromlist=["LeadSignal"]).LeadSignal.NEGATIVE_FEEDBACK,
                    client_id=enrollment.client_id,
                )
            except Exception as e:
                logger.warning(f"Lead score update failed: {e}")

        logger.info(f"[v] Feedback recorded for enrollment {enrollment_id}: score={score}, delta={score_delta}")
        return {"status": "recorded", "score": score, "score_delta": score_delta}

    async def _send(self, enrollment: AppointmentNurtureEnrollment, message: str) -> bool:
        if not self.message_sender:
            logger.warning(f"No message sender configured, would send to {enrollment.phone_number}: {message}")
            return True
        try:
            sent = await self.message_sender(enrollment.phone_number, message)
            if sent:
                logger.info(f"[v] Nurture message sent to {enrollment.phone_number}: {message[:50]}...")
            return sent
        except Exception as e:
            logger.error(f"Failed to send nurture message to {enrollment.phone_number}: {e}")
            return False


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

appointment_nurture = AppointmentNurture()
