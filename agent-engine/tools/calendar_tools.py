import logging
from datetime import datetime, timezone
import pytz
from typing import Dict, Any
from tools.dispatcher import tool_dispatcher
from db import async_session, Appointment, Contact
from sqlalchemy import select

logger = logging.getLogger("calendar_tools")

DEFAULT_TZ = "Asia/Kolkata"


def _phone_hash(phone: str) -> str:
    import hashlib
    return hashlib.sha256(phone.strip().encode()).hexdigest()


async def check_calendar(date: str, timezone_str: str = DEFAULT_TZ, client_id: int = 1):
    """
    Check available/booked slots for a date (YYYY-MM-DD) for this business.
    """
    try:
        pytz.timezone(timezone_str)  # validate
        async with async_session() as session:
            result = await session.execute(
                select(Appointment).where(
                    Appointment.appointment_date == date,
                    Appointment.client_id == int(client_id),
                )
            )
            appts = result.scalars().all()

            if not appts:
                return {"status": "available",
                        "message": f"{date} is fully open ({timezone_str})."}
            booked = [f"{a.appointment_time}" for a in appts if a.appointment_time]
            return {"status": "partial", "booked_slots": booked,
                    "message": f"Some slots are taken on {date}. Booked times: {', '.join(booked)}."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def book_appointment(phone_number: str, date: str, time: str,
                           client_id: int = 1, title: str = "",
                           notes: str = "", timezone_str: str = DEFAULT_TZ):
    """
    Book an appointment for a customer. Saves it in the database so the
    owner can see it in the dashboard / GET /api/appointments.
    """
    try:
        pytz.timezone(timezone_str)  # validate
        phone = phone_number.strip()
        async with async_session() as session:
            # 1. Double-booking check (per business)
            result = await session.execute(
                select(Appointment).where(
                    Appointment.appointment_date == date,
                    Appointment.appointment_time == time,
                    Appointment.client_id == int(client_id),
                    Appointment.status.in_(["scheduled", "confirmed"]),
                )
            )
            if result.scalar_one_or_none():
                return {"status": "error",
                        "message": "This slot is already booked. Please choose another time."}

            # 2. Link to the contact so the owner knows who booked
            phash = _phone_hash(phone)
            cres = await session.execute(
                select(Contact).where(Contact.phone_hash == phash,
                                      Contact.client_id == int(client_id))
            )
            contact = cres.scalar_one_or_none()

            appt = Appointment(
                client_id=int(client_id),
                contact_id=contact.id if contact else None,
                phone_number=phone,
                phone_hash=phash,
                title=title or "Appointment",
                description=notes or None,
                appointment_date=date,
                appointment_time=time,
                status="scheduled",
                sector_metadata={"timezone": timezone_str},
            )
            session.add(appt)
            await session.commit()
            await session.refresh(appt)
            logger.info("Appointment #%s booked for client %s: %s %s %s",
                        appt.id, client_id, phone, date, time)
            return {"status": "success", "appointment_id": appt.id,
                    "message": f"Booked {title or 'appointment'} for {date} at {time} ({timezone_str})."}
    except Exception as e:
        logger.error("book_appointment failed: %s", e, exc_info=True)
        return {"status": "error", "message": str(e)}


tool_dispatcher.register("check_calendar", check_calendar)
tool_dispatcher.register("book_appointment", book_appointment)
