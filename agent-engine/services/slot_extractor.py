"""Deterministic Hinglish/Hindi/English slot extractor.

Parses date / time / guests / quantity / address directly from messy
customer messages (e.g. "Mujhe kal shaam 7 baje 4 logon ke liye table
book karni hai") without an LLM call, so bookings can complete in <1s.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# ── vocabulary ────────────────────────────────────────────────────────────────
DAY_WORDS = {
    "aaj": 0, "today": 0,
    "kal": 1, "tomorrow": 1,
    "parso": 2, "day after tomorrow": 2,
}
WEEKDAYS = {
    "monday": 0, "somvar": 0, "somwar": 0,
    "tuesday": 1, "mangalvar": 1, "mangalwar": 1,
    "wednesday": 2, "budhvar": 2, "budhwar": 2,
    "thursday": 3, "guruvar": 3, "guruwar": 3,
    "friday": 4, "shukravar": 4, "shukrawar": 4, "jumma": 4,
    "saturday": 5, "shanivar": 5, "shaniwar": 5,
    "sunday": 6, "ravivar": 6, "itwar": 6,
}
PART_OF_DAY = {
    "shaam": "pm", "shyam": "pm", "evening": "pm", "saam": "pm",
    "raat": "pm", "night": "pm",
    "subah": "am", "morning": "am",
    "dopahar": "pm", "dopehar": "pm", "afternoon": "pm",
}
NUM_WORDS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4,
    "chaar": 4, "four": 4, "panch": 5, "paanch": 5, "five": 5, "cheh": 6,
    "chhe": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8,
    "nau": 9, "nine": 9, "das": 10, "ten": 10, "barah": 12, "twelve": 12,
}

BOOKING_HINTS = re.compile(
    r"\b(book|booking|reserve|reservation|table|appointment|slot)\b", re.I)
ORDER_HINTS = re.compile(
    r"\b(order|delivery|deliver|parcels?|khana|mangwa\w*|mangvado|mangwana|"
    r"bhej\w*|bhijwa\w*)\b", re.I)


def _num(token: str) -> Optional[int]:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return NUM_WORDS.get(token)


def extract_date(text: str, now: Optional[datetime] = None) -> Optional[str]:
    now = now or datetime.now()
    low = text.lower()

    for word, offset in DAY_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            return (now + timedelta(days=offset)).strftime("%Y-%m-%d")

    # "next monday" / "agle monday"
    m = re.search(r"\b(?:next|agle|agla|coming)\s+(" + "|".join(WEEKDAYS) + r")\b", low)
    base = 7
    if not m:
        m = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", low)
        base = 0
    if m:
        target = WEEKDAYS[m.group(1)]
        delta = (target - now.weekday()) % 7
        if base == 7 and delta < 7:
            delta = delta or 7
        elif delta == 0:
            delta = 7
        return (now + timedelta(days=delta)).strftime("%Y-%m-%d")

    # explicit dates: 2026-09-10, "10 sep", "10 september"
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", low)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            return None
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
              "sep", "oct", "nov", "dec"]
    m = re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+([a-z]{3})[a-z]*\b", low)
    if m and m.group(2)[:3] in months:
        try:
            d = datetime(now.year, months.index(m.group(2)[:3]) + 1, int(m.group(1)))
            if d < now:
                d = d.replace(year=now.year + 1)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def extract_time(text: str) -> Optional[str]:
    low = text.lower()

    # explicit am/pm: "7 pm", "7:30 pm"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", low)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
        return f"{hour:02d}:{m.group(2) or '00'}"

    part = next((v for k, v in PART_OF_DAY.items() if re.search(rf"\b{k}\b", low)), None)

    # "shaam 7 baje" / "7 baje"
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:baje|bje|o'?clock|hours)\b", low)
    if not m:
        m = re.search(
            r"\b(?:shaam|shyam|raat|subah|morning|evening|dopahar|afternoon)"
            r"\s+(\d{1,2})(?::(\d{2}))?\b", low)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if 1 <= hour <= 12:
            if part == "pm" and hour != 12:
                hour += 12
            elif part == "am" and hour == 12:
                hour = 0
            elif part is None and hour <= 6:
                hour += 12  # bare "5 baje" -> evening
        if 0 <= hour <= 23 and minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # military "19:00"
    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", low)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return None


def extract_guests(text: str) -> Optional[int]:
    low = text.lower()
    m = re.search(
        r"\b(\d{1,3}|" + "|".join(NUM_WORDS) + r")\s*"
        r"(?:log|logo|logon|people|persons?|guests?|pax|members?)\b", low)
    if m:
        return _num(m.group(1))
    m = re.search(
        r"\btable\s*(?:for|of)\s*(\d{1,3}|" + "|".join(NUM_WORDS) + r")\b", low)
    if m:
        return _num(m.group(1))
    return None


ADDRESS_RE = re.compile(
    r"(?:delivery|deliver|bhejo|bhej do|bhijwa\w*)\s*(?:kar\w*)?\s*(?:de\w*)?\s*"
    r"(?:in|at|me|mein|to)?\s*([A-Za-z][A-Za-z0-9 .,-]{2,60})",
    re.I)


def extract_items(text: str, drop_address: bool = True) -> List[Dict]:
    """Extract '2 margherita pizza aur cold coffee' (qty defaults to 1)."""
    work = text
    if drop_address:
        m = ADDRESS_RE.search(work)
        if m:
            work = work[:m.start()] + work[m.end():]

    qty_word = r"(?:\d{1,2}|" + "|".join(NUM_WORDS) + r")"
    items: List[Dict] = []
    for seg in re.split(r",| and | aur | \+ ", work):
        seg = seg.strip(" .!?")
        if not seg:
            continue
        m = re.match(
            rf"^(?:bhai|bhaiya|please|plz|pls|hi|hello|hey|ji)?\s*"
            rf"({qty_word})\s*(?:x\s*)?(?:plates?|cups?|pieces?|pcs|kgs?|glasses?)?\s*"
            r"(.+)$", seg, re.I)
        if m:
            qty = _num(m.group(1))
            name = m.group(2)
        else:
            # qty-less segment only counts if it's not the first fillers
            m2 = re.match(rf"^(?:plates?|cups?|pieces?|pcs|kgs?|glasses?)?\s*([a-z][a-z0-9 ]{{2,40}})$",
                          seg, re.I)
            if not m2:
                continue
            qty, name = 1, m2.group(1)
        name = re.sub(r"\b(ka|ki|ke|dena|dedo|kar|kardo|do|lana|la|chahiye|"
                      r"mangwa|mangvado|mangwana|delivery|deliver|bhejo|bhej|"
                      r"de|dijiye|me|mein)\b", "", name, flags=re.I).strip(" .,-")
        if not qty or len(name) < 3:
            continue
        if re.search(r"\b(log|logo|logon|people|guests?|baje|bje|table|book)\b",
                     name, re.I):
            continue
        items.append({"name": name, "qty": qty})
    return items


def extract_address(text: str) -> Optional[str]:
    m = ADDRESS_RE.search(text)
    if m:
        addr = m.group(1).strip(" .,-")
        addr = re.split(r"\b(?:kar|kardo|dena|dedo|chahiye|asap|jaldi)\b",
                        addr, flags=re.I)[0].strip(" .,-")
        return addr or None
    return None


def classify_intent(text: str) -> Optional[str]:
    booking = bool(BOOKING_HINTS.search(text))
    ordering = bool(ORDER_HINTS.search(text))
    if booking and not ordering:
        return "booking"
    if ordering and not booking:
        return "order"
    if booking and ordering:
        return "order" if extract_items(text) else "booking"
    return None


def extract_slots(text: str, now: Optional[datetime] = None) -> Dict:
    """Main entry: full slot dict for a customer message."""
    return {
        "intent_hint": classify_intent(text),
        "date": extract_date(text, now),
        "time": extract_time(text),
        "guests": extract_guests(text),
        "items": extract_items(text),
        "address": extract_address(text),
    }

