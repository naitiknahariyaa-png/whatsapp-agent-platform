"""Tests for growth-loop modules (lead funnel + appointment nurture)."""
from lead_funnel import LeadFunnel
from appointment_nurture import AppointmentNurture


def test_lead_funnel_opt_out_detection():
    lf = LeadFunnel(message_sender=None)
    assert lf.is_opt_out_message("stop") is True
    assert lf.is_opt_out_message("unsubscribe") is True
    assert lf.is_opt_out_message("hi I want to book") is False


def test_appointment_nurture_parse_datetime():
    an = AppointmentNurture(message_sender=None)
    dt = an._parse_appointment_datetime("2026-09-01", "15:30")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 9 and dt.day == 1
    assert dt.hour == 15 and dt.minute == 30


def test_appointment_nurture_parse_datetime_invalid():
    an = AppointmentNurture(message_sender=None)
    assert an._parse_appointment_datetime("not-a-date", None) is None
