"""
Scheduling & Appointments Functions
Timezone bugs are the #1 source of 'the bot booked the wrong time' complaints.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone
from typing import Any, Dict, List, Optional
import pytz
from icalendar import Calendar, Event

logger = logging.getLogger(__name__)


# =============================================================================
# 6.1 to_business_timezone / to_user_timezone — Explicit conversion helpers
# =============================================================================
def to_business_timezone(
    dt: datetime,
    business_tz: str = "Asia/Kolkata",
    user_tz: Optional[str] = None,
) -> datetime:
    """
    Convert a datetime to business timezone.
    The #1 source of 'the bot booked the wrong time' bugs — tiny function, huge trust impact.
    
    Args:
        dt: Datetime to convert (assumed UTC if naive)
        business_tz: Business timezone (default IST)
        user_tz: User's timezone if dt is in user's local time
    
    Returns:
        Timezone-aware datetime in business timezone
    """
    # If dt is naive, assume it's in user_tz or UTC
    if dt.tzinfo is None:
        if user_tz:
            user_timezone = pytz.timezone(user_tz)
            dt = user_timezone.localize(dt)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    
    # Convert to business timezone
    biz_tz = pytz.timezone(business_tz)
    return dt.astimezone(biz_tz)


def to_user_timezone(
    dt: datetime,
    user_tz: str,
    business_tz: str = "Asia/Kolkata",
) -> datetime:
    """
    Convert business datetime to user's timezone for display.
    
    Args:
        dt: Business timezone-aware datetime
        user_tz: User's timezone
        business_tz: Business timezone (default IST)
    
    Returns:
        Datetime in user's timezone
    """
    # Ensure dt is in business timezone
    if dt.tzinfo is None:
        dt = pytz.timezone(business_tz).localize(dt)
    elif str(dt.tzinfo) != business_tz:
        dt = dt.astimezone(pytz.timezone(business_tz))
    
    # Convert to user timezone
    user_timezone = pytz.timezone(user_tz)
    return dt.astimezone(user_timezone)


def parse_user_datetime(
    date_str: str,
    time_str: str,
    user_tz: str = "Asia/Kolkata",
) -> datetime:
    """
    Parse user-provided date/time into timezone-aware datetime.
    
    Args:
        date_str: Date in YYYY-MM-DD format
        time_str: Time in HH:MM format (24h)
        user_tz: User's timezone
    
    Returns:
        Timezone-aware datetime in user's timezone
    """
    try:
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        user_tz_obj = pytz.timezone(user_tz)
        return user_tz_obj.localize(naive)
    except ValueError as e:
        raise ValueError(f"Invalid date/time format: {date_str} {time_str}") from e


# =============================================================================
# 6.2 check_double_booking — Prevents embarrassing conflicts
# =============================================================================
@dataclass
class TimeSlot:
    start: datetime
    end: datetime
    buffer_minutes: int = 15


async def check_double_booking(
    slot: TimeSlot,
    calendar_id: str,
    db_session=None,
    exclude_appointment_id: Optional[str] = None,
) -> bool:
    """
    Verifies no conflict before confirming.
    Prevents the most embarrassing possible bug: double-booked appointments.
    
    Args:
        slot: Time slot to check
        calendar_id: Calendar identifier (business/client)
        db_session: Optional DB session
        exclude_appointment_id: Appointment ID to exclude (for rescheduling)
    
    Returns:
        True if conflict exists, False if slot is free
    """
    # Add buffer to slot
    buffered_start = slot.start - timedelta(minutes=slot.buffer_minutes)
    buffered_end = slot.end + timedelta(minutes=slot.buffer_minutes)
    
    if db_session:
        from db import Appointment
        from sqlalchemy import select, and_
        
        query = select(Appointment).where(
            and_(
                Appointment.calendar_id == calendar_id,
                Appointment.status.in_(["scheduled", "confirmed"]),
                # Overlap check: existing.start < new.end AND existing.end > new.start
                Appointment.start_time < buffered_end,
                Appointment.end_time > buffered_start,
            )
        )
        
        if exclude_appointment_id:
            query = query.where(Appointment.id != exclude_appointment_id)
        
        result = await db_session.execute(query)
        conflict = result.scalar_one_or_none()
        return conflict is not None
    
    # Fallback: check in-memory/Redis cache
    # This would need a separate scheduling cache implementation
    return False


# =============================================================================
# 6.3 generate_ics_invite — Calendar file attachment
# =============================================================================
@dataclass
class AppointmentDetails:
    id: str
    title: str
    description: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    organizer_email: Optional[str] = None
    organizer_name: Optional[str] = None
    attendee_email: Optional[str] = None
    attendee_name: Optional[str] = None
    timezone: str = "Asia/Kolkata"
    reminder_minutes: List[int] = None  # e.g., [1440, 60, 15] = 1 day, 1h, 15min


def generate_ics_invite(appointment: AppointmentDetails) -> bytes:
    """
    Builds a calendar file attachment.
    Small polish feature, meaningfully increases show-up rate.
    
    Args:
        appointment: AppointmentDetails object
    
    Returns:
        ICS file content as bytes
    """
    cal = Calendar()
    cal.add("prodid", "-//WhatsApp Agent Platform//Appointment//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "REQUEST")
    
    event = Event()
    event.add("uid", appointment.id)
    event.add("dtstamp", datetime.now(timezone.utc))
    event.add("dtstart", appointment.start)
    event.add("dtend", appointment.end)
    event.add("summary", appointment.title)
    event.add("description", appointment.description)
    
    if appointment.location:
        event.add("location", appointment.location)
    
    if appointment.organizer_email:
        event.add("organizer", f"mailto:{appointment.organizer_email}", parameters={"cn": appointment.organizer_name})
    
    if appointment.attendee_email:
        event.add("attendee", f"mailto:{appointment.attendee_email}", parameters={"cn": appointment.attendee_name, "role": "REQ-PARTICIPANT"})
    
    # Add reminders
    if appointment.reminder_minutes:
        for minutes in appointment.reminder_minutes:
            alarm = icalendar.Alarm()
            alarm.add("action", "DISPLAY")
            alarm.add("description", f"Reminder: {appointment.title}")
            alarm.add("trigger", timedelta(minutes=-minutes))
            event.add_component(alarm)
    
    cal.add_component(event)
    return cal.to_ical()


# =============================================================================
# 6.4 detect_reschedule_intent — Distinguishes cancel vs reschedule
# =============================================================================
RESCHEDULE_KEYWORDS = [
    "reschedule", "move", "change", "shift", "different time",
    "another time", "later", "earlier", "postpone", "rebook",
    "can we do", "can we move", "change to", "switch to",
]

CANCEL_KEYWORDS = [
    "cancel", "cancellation", "call off", "not coming",
    "don't need", "not needed", "no longer", "stop",
    "withdraw", "abort",
]

def detect_reschedule_intent(message_text: str) -> str:
    """
    Distinguishes 'cancel' vs 'can we move it'.
    Without this, a reschedule request gets misread as a cancellation.
    
    Args:
        message_text: User's message
    
    Returns:
        "reschedule", "cancel", or "unknown"
    """
    text = message_text.lower()
    
    # Check for explicit reschedule language
    for kw in RESCHEDULE_KEYWORDS:
        if kw in text:
            return "reschedule"
    
    # Check for explicit cancellation
    for kw in CANCEL_KEYWORDS:
        if kw in text:
            return "cancel"
    
    # Check for time expressions (suggests reschedule)
    time_patterns = [
        r"\d{1,2}:\d{2}",  # 3:00
        r"\d{1,2}\s*(am|pm)",  # 3pm
        r"(tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        r"next week|this week",
    ]
    
    for pattern in time_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return "reschedule"
    
    return "unknown"


# =============================================================================
# 6.5 mark_no_show — Auto-flags missed appointments
# =============================================================================
async def mark_no_show(
    appointment_id: str,
    grace_period_minutes: int = 30,
    db_session=None,
) -> bool:
    """
    Auto-flags missed appointments after time window passes.
    Feeds directly into re-engagement/no-show follow-up loop.
    
    Args:
        appointment_id: Appointment to check
        grace_period_minutes: Minutes after scheduled end to wait
        db_session: Database session
    
    Returns:
        True if marked as no-show, False otherwise
    """
    if not db_session:
        return False
    
    from db import Appointment
    from sqlalchemy import select, and_
    
    result = await db_session.execute(
        select(Appointment).where(Appointment.id == appointment_id)
    )
    appointment = result.scalar_one_or_none()
    
    if not appointment:
        return False
    
    # Check if appointment time has passed + grace period
    now = datetime.now(timezone.utc)
    appointment_end = appointment.end_time
    
    # Ensure timezone awareness
    if appointment_end.tzinfo is None:
        appointment_end = appointment_end.replace(tzinfo=timezone.utc)
    
    cutoff = appointment_end + timedelta(minutes=grace_period_minutes)
    
    if now >= cutoff and appointment.status in ["scheduled", "confirmed"]:
        appointment.status = "no_show"
        appointment.no_show_at = now
        await db_session.commit()
        
        # Trigger no-show follow-up
        logger.info(f"Appointment {appointment_id} marked as no-show")
        return True
    
    return False