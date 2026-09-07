"""
Report-based broadcast: read a business-contacts report (XLSX/CSV), generate
one on-brand outreach message per row from fixed generation rules, and
(optionally) send via the BroadcastEngine.

Generation rules (enforced in code, ladder ensures <=160 chars):
  Greeting      Hi {business_name|there},
  Pitch line    Unlock AI-powered WhatsApp automation for your business
                with our all-in-one platform
  Benefits      short comma-separated phrase ending with a period
  How to get it Reply YES for a free demo!
  Tone          follows brand_voice (emojis only for casual/playful)
  Length        <=160 chars; benefits dropped first, then greeting degrades
                to "Hi there!" — the CTA is never cut.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("report_broadcast")

MAX_LEN = 160
REQUIRED_LINE = ("Unlock AI-powered WhatsApp automation for your business "
                 "with our all-in-one platform")
CTA = "Reply YES for a free demo!"

BENEFITS = {
    "shops": "auto-replies, orders & leads on autopilot",
    "retail": "auto-replies, orders & leads on autopilot",
    "hotels": "instant booking replies & guest support 24x7",
    "restaurant": "instant order replies & table bookings 24x7",
    "doctors": "appointment booking & patient reminders",
    "salon": "instant bookings & offers that fill your chairs",
    "default": "instant replies, bookings & leads 24x7",
}

_COLUMN_ALIASES = {
    "category": {"category", "type", "segment", "vertical", "industry"},
    "business_name": {"business name", "business_name", "businessname",
                      "name", "business", "shop name", "shop_name"},
    "phone": {"contact number", "contact_number", "contactnumber", "phone",
              "phone number", "mobile", "mobile number", "contact",
              "whatsapp", "whatsapp number", "number"},
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def load_report(path: str) -> List[Dict[str, Any]]:
    """Read a contacts report; rows mapped to category/business_name/phone."""
    p = str(path).lower()
    if p.endswith(".xlsx") or p.endswith(".xls"):
        return _load_xlsx(path)
    return _load_csv(path)


def _load_csv(path: str) -> List[Dict[str, Any]]:
    import csv
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header: List[str] = []
        for i, raw in enumerate(reader):
            if not raw:
                continue
            if i == 0:
                header = [_norm(c) for c in raw]
                continue
            m = _map_row(dict(zip(header, [c.strip() for c in raw])))
            if m:
                rows.append(m)
    return rows


def _load_xlsx(path: str) -> List[Dict[str, Any]]:
    """Read an xlsx without external deps (handles inlineStr + shared strings)."""
    import zipfile
    import xml.etree.ElementTree as ET
    NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    tag = lambda name: f"{{{NS}}}{name}"  # noqa: E731
    with zipfile.ZipFile(path) as z:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            with z.open("xl/sharedStrings.xml") as f:
                root = ET.parse(f).getroot()
                shared = ["".join(t.text or "" for t in si.iter(tag("t")))
                          for si in root.findall(tag("si"))]
        with z.open("xl/worksheets/sheet1.xml") as f:
            root = ET.parse(f).getroot()

    table = root.find(tag("sheetData"))
    if table is None:
        return []
    grid: List[List[str]] = []
    first_cols: List[str] = []
    for row_el in table.findall(tag("row")):
        cells: Dict[str, str] = {}
        for c in row_el.findall(tag("c")):
            ref = c.get("r", "A1")
            col = re.match(r"([A-Z]+)", ref).group(1)
            if c.get("t") == "inlineStr":
                is_el = c.find(tag("is"))
                val = "".join(t.text or "" for t in is_el.findall(tag("t"))) \
                    if is_el is not None else ""
            else:
                v = c.find(tag("v"))
                val = v.text or "" if v is not None else ""
                if c.get("t") == "s" and val.isdigit() and int(val) < len(shared):
                    val = shared[int(val)]
            cells[col] = (val or "").strip()
        if not first_cols:
            first_cols = list(cells.keys())
        grid.append([cells.get(k, "") for k in first_cols])

    if len(grid) < 2:
        return []
    header = [_norm(h) for h in grid[0]]
    out: List[Dict[str, Any]] = []
    for raw in grid[1:]:
        m = _map_row(dict(zip(header, raw)))
        if m:
            out.append(m)
    return out


def _map_row(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mapped: Dict[str, str] = {}
    for key, aliases in _COLUMN_ALIASES.items():
        for col, val in row.items():
            if _norm(str(col)) in aliases and _norm(str(val)):
                mapped[key] = str(val).strip()
                break
    if not mapped.get("business_name") or not mapped.get("phone"):
        return None
    out = dict(row)
    out.update(mapped)
    out["category"] = _norm(mapped.get("category", "")) or "default"
    return out


def normalize_phone(raw: str) -> Optional[str]:
    """E.164-normalize a contact number (+91 default); None if invalid."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "91" + digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    if not (10 <= len(digits) <= 15):
        return None
    return "+" + digits


# ── Message generation (rules ladder) ────────────────────────────────────────
def _benefits(category: str) -> str:
    return BENEFITS.get(_norm(category)) or BENEFITS["default"]


def build_outreach_message(business_name: str, category: str = "",
                           brand_voice: str = "playful") -> Dict[str, Any]:
    """Assemble the message per the generation rules ladder (<=160 chars)."""
    name = (business_name or "").strip()
    benefit = _benefits(category)
    sweet = " ✨" if _norm(brand_voice) in ("casual", "playful") else ""
    ladder = [
        f"Hi {name}! {REQUIRED_LINE} - {benefit}. {CTA}{sweet}",
        f"Hi {name}! {REQUIRED_LINE}. {CTA}{sweet}",
        f"Hi there! {REQUIRED_LINE} - {benefit}. {CTA}{sweet}",
        f"Hi there! {REQUIRED_LINE}. {CTA}{sweet}",
    ]
    for text in ladder:
        if len(text) <= MAX_LEN:
            return {"text": text, "chars": len(text), "within_limit": True}
    return {"text": ladder[-1][:MAX_LEN], "chars": MAX_LEN,
            "within_limit": True, "truncated": True}


def build_all(rows: List[Dict[str, Any]], brand_voice: str = "playful"
              ) -> List[Dict[str, Any]]:
    """Generate messages for every row; marks invalid/duplicate numbers."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for r in rows:
        phone = normalize_phone(r.get("phone", ""))
        duplicate = bool(phone) and phone in seen
        if phone:
            seen.add(phone)
        msg = build_outreach_message(r.get("business_name", ""),
                                     r.get("category", ""), brand_voice)
        entry = {"category": r.get("category", ""),
                 "business_name": r.get("business_name", ""),
                 "phone": phone, "raw_phone": r.get("phone", ""),
                 "valid": bool(phone) and not duplicate,
                 **msg}
        if duplicate:
            entry["reason"] = "duplicate number"
        elif phone is None:
            entry["reason"] = "invalid number"
        out.append(entry)
    return out


async def _already_sent(client_id: int, phone: str, text: str) -> bool:
    """True if an outgoing Message with this exact text was recorded already
    (durable dedup so re-runs never double-send)."""
    from sqlalchemy import select
    from db import async_session, Message
    async with async_session() as session:
        res = await session.execute(
            select(Message).where(Message.direction == "outgoing",
                                  Message.client_id == client_id,
                                  Message.content == text).limit(1))
        return res.scalar_one_or_none() is not None


async def send_valid(messages: List[Dict[str, Any]], client_id: int = 1,
                     list_name: str = "report-outreach") -> Dict[str, Any]:
    """Send the valid messages with durable per-send tracking.

    Dedup: a row whose content equals the message text is treated as already
    sent, so interrupted/re-run batches never double-deliver. Each actual
    send is recorded to the messages table (direction='outreach')."""
    from broadcast import broadcast_engine
    from db import save_message
    from outbound_limiter import send_whatsapp
    from db import async_session
    valid = [m for m in messages if m.get("valid")]
    if not valid:
        return {"ok": False, "error": "no valid rows to send"}

    phones = [m["phone"] for m in valid]
    created = await broadcast_engine.create_list(
        list_name, phones,
        description=f"report outreach {len(phones)} contacts")

    sent, skipped = 0, 0
    for m in valid:
        if await _already_sent(client_id, m["phone"], m["text"]):
            skipped += 1
            continue
        ok = await send_whatsapp(m["phone"], m["text"], client_id=client_id)
        if ok:
            try:
                await save_message(phone_number=m["phone"], content=m["text"],
                                   direction="outgoing", client_id=client_id)
            except Exception as e:
                logger.warning("[!] record send failed for %s: %s", m["phone"], e)
            sent += 1
    return {"ok": True, "total": len(valid), "sent": sent,
            "skipped_existing": skipped,
            "list": created if isinstance(created, str) else list_name}