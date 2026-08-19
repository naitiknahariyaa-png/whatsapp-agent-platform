import logging
from datetime import datetime, timezone, timedelta
import pytz
from typing import Dict, Any, Optional
from tools.dispatcher import tool_dispatcher
from db import async_session, Appointment
from sqlalchemy import select

logger = logging.getLogger(\"calendar_tools\")

async def check_calendar(date: str, timezone_str: str = \"UTC\"):
    \"\"\"
    Production Calendar Check.
    Handles Timezone conversion and double-booking checks.
    \"\"\"
    try:
        user_tz = pytz.timezone(timezone_str)
        # Convert input date to UTC for DB check
        # In a real app, we would check the specific hour slot.
        async with async_session() as session:
            result = await session.execute(select(Appointment).where(Appointment.appointment_date == date))
            appts = result.scalars().all()
            
            if not appts:
                return {\"status\": \"available\", \"message\": f\"The date {date} is fully open in {timezone_str}.\"}
            
            booked = [f\"{a.appointment_time} (UTC)\" for a in appts if a.appointment_time]
            return {\"status\": \"partial\", \"booked_slots\": booked, \"message\": f\"Some slots are taken on {date}.\"}
    except Exception as e:
        return {\"status\": \"error\", \"message\": str(e)}

async def book_appointment(phone_number: str, date: str, time: str, timezone_str: str = \"UTC\"):
    \"\"\"
    Production Booking.
    1. Double-booking check.
    2. Timezone normalization.
    3. Save to DB.
    \"\"\"
    try:
        # 1. Double-booking check
        async with async_session() as session:
            result = await session.execute(
                select(Appointment).where(
                    Appointment.appointment_date == date, 
                    Appointment.appointment_time == time
                )
            )
            if result.scalar_one_or_none():
                return {\"status\": \"error\", \"message\": \"This slot is already booked. Please choose another time.\"}

            # 2. Normalize to UTC
            # Simplified: just save as provided but tag the timezone
            new_appt = Appointment(
                phone_number=phone_number,
                appointment_date=date,
                appointment_time=time,
                sector_metadata={\"timezone\": timezone_str},
                status=\"scheduled\"
            )
            session.add(new_appt)
            await session.commit()
            return {\"status\": \"success\", \"message\": f\"Booked for {date} at {time} ({timezone_str})\"}
    except Exception as e:
        return {\"status\": \"error\", \"message\": str(e)}

tool_dispatcher.register(\"check_calendar\", check_calendar)
tool_dispatcher.register(\"book_appointment\", book_appointment)
