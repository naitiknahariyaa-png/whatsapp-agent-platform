"""Tests for the deterministic Hinglish slot extractor (Phase 1)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from services.slot_extractor import (
    extract_slots, extract_date, extract_time, extract_guests,
    extract_items, extract_address, classify_intent,
)

NOW = datetime(2026, 9, 4, 12, 0)  # Friday


def test_hinglish_table_booking():
    s = extract_slots("Mujhe kal shaam 7 baje 4 logon ke liye table book karni hai", NOW)
    assert s["intent_hint"] == "booking"
    assert s["date"] == "2026-09-05"           # kal = tomorrow
    assert s["time"] == "19:00"                # shaam 7 baje
    assert s["guests"] == 4                    # 4 logon


def test_english_booking():
    s = extract_slots("Book a table for 4 tomorrow at 7 pm", NOW)
    assert s["intent_hint"] == "booking"
    assert s["date"] == "2026-09-05"
    assert s["time"] == "19:00"
    assert s["guests"] == 4


def test_order_with_delivery():
    s = extract_slots(
        "Bhai 2 Margherita pizza aur cold coffee delivery kar do Andheri West me", NOW)
    assert s["intent_hint"] == "order"
    items = {i["name"].lower(): i["qty"] for i in s["items"]}
    assert items.get("margherita pizza") == 2
    assert items.get("cold coffee") == 1
    assert "andheri west" in (s["address"] or "").lower()


def test_hindi_number_guests():
    assert extract_guests("teen logon ke liye") == 3
    assert extract_guests("table for 12") == 12


def test_time_variants():
    assert extract_time("kal shaam 7 baje") == "19:00"
    assert extract_time("subah 9 baje") == "09:00"
    assert extract_time("raat 11 baje") == "23:00"
    assert extract_time("7:30 pm") == "19:30"
    assert extract_time("meeting at 19:00") == "19:00"
    assert extract_time("5 baje") == "17:00"   # bare hour -> evening


def test_date_variants():
    assert extract_date("kal", NOW) == "2026-09-05"
    assert extract_date("aaj", NOW) == "2026-09-04"
    assert extract_date("parso", NOW) == "2026-09-06"
    assert extract_date("next monday", NOW) == "2026-09-07"
    assert extract_date("10 sep", NOW) == "2026-09-10"
    assert extract_date("2026-12-25", NOW) == "2026-12-25"


def test_no_false_positive_intent():
    assert classify_intent("hello, what are your timings?") is None
    assert classify_intent("what is the price of butter chicken?") is None


def test_full_order_slots():
    s = extract_slots("mangwa do 3 plate biryani delivery kar do Satinagar me kal", NOW)
    assert s["intent_hint"] == "order"
    assert s["date"] == "2026-09-05"
    assert any("biryani" in i["name"] for i in s["items"])
