"""
Background scheduler — runs the drip-campaign engine loop and appointment reminders.

Uses plain asyncio tasks (no external deps) started from the FastAPI lifespan.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from config import settings
from logging_setup import get_logger

logger = get_logger("scheduler")

REMINDER_CHECK_INTERVAL = 60          # seconds between reminder sweeps
REMINDER_LEAD_MINUTES = 60            # remind 1 hour before appointment

_tasks: list = []


async def _send_whatsapp(phone_number: str, message: str) -> bool:
    """Send an outbound WhatsApp message via the bridge."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.whatsapp_bridge_url}/send",
                json={"to": phone_number, "message": message},
                timeout=10,
            )
            return resp.status_code == 200
    except Exception as e:
        logger.warning(f"Bridge send failed for {phone_number}: {e}")
        return False


async def _appointment_reminder_loop():
    """Every minute, find appointments starting within the lead window and remind."""
    from db import async_session, Appointment

    reminded: set = set()  # appointment ids already reminded this process
    while True:
        try:
            now = datetime.now(timezone.utc)
            today = now.strftime("%Y-%m-%d")
            async with async_session() as session:
                result = await session.execute(
                    select(Appointment).where(
                        Appointment.status == "scheduled",
                        Appointment.appointment_date == today,
                    )
                )
                for appt in result.scalars().all():
                    if appt.id in reminded or not appt.appointment_time:
                        continue
                    try:
                        appt_dt = datetime.strptime(
                            f"{appt.appointment_date} {appt.appointment_time}", "%Y-%m-%d %H:%M"
                        ).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    minutes_away = (appt_dt - now).total_seconds() / 60
                    if 0 < minutes_away <= REMINDER_LEAD_MINUTES:
                        msg = (f"⏰ Reminder: you have an appointment"
                               f"{' — ' + appt.title if appt.title else ''} "
                               f"at {appt.appointment_time} today.")
                        if await _send_whatsapp(appt.phone_number, msg):
                            reminded.add(appt.id)
                            logger.info(f"Sent reminder for appointment {appt.id}")
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        await asyncio.sleep(REMINDER_CHECK_INTERVAL)


async def start_scheduler():
    """Start all background loops. Call from FastAPI lifespan."""
    # 1. Drip campaign engine loop (uses its own start())
    try:
        from drip_campaigns import engine as drip_engine
        await drip_engine.start(interval=5.0)
        logger.info("[v] Drip campaign engine loop started")
    except Exception as e:
        logger.warning(f"Drip engine not started: {e}")

    # 2. Appointment reminders
    _tasks.append(asyncio.create_task(_appointment_reminder_loop()))
    logger.info("[v] Appointment reminder loop started")


async def stop_scheduler():
    """Cancel background loops. Call from FastAPI lifespan shutdown."""
    try:
        from drip_campaigns import engine as drip_engine
        await drip_engine.stop()
    except Exception:
        pass
    for t in _tasks:
        t.cancel()
    _tasks.clear()
    logger.info("[i] Scheduler stopped")
