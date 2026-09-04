#!/usr/bin/env python3
"""
WhatsApp Agent Platform — CLI command implementations.

Single source of truth for the ops sub-commands:
    start-server, generate-report, run-reengage, stop-reengage,
    list-alerts, trigger-alerts, approval-request, approval-decision

Both `cli.py` (argparse) and `wap-cli.py` (interactive menu) import from here,
so the CLI drives the SAME FastAPI endpoints the UI uses — no direct DB access,
no duplicated business logic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

ROOT = Path(__file__).parent.resolve()
AGENT_ENGINE = ROOT / "agent-engine"
API_BASE = os.getenv("WAP_API_BASE", f"http://127.0.0.1:{os.getenv('PORT', '8000')}")
TIMEOUT = 60.0


# ── Auth token ────────────────────────────────────────────────────────────────

def get_token(token: Optional[str] = None) -> Optional[str]:
    """Resolve a JWT from --token arg, WAP_TOKEN env, or WAP_EMAIL/WAP_PASSWORD login.
    On successful login, store the token in the WAP_TOKEN environment variable for reuse."""
    token = token or os.getenv("WAP_TOKEN", "")
    if token:
        return token
    email = os.getenv("WAP_EMAIL", "")
    password = os.getenv("WAP_PASSWORD", "")
    if not (email and password):
        # Prompt user for credentials interactively
        try:
            email = input('WAP_EMAIL: ').strip()
            password = input('WAP_PASSWORD: ').strip()
        except EOFError:
            return None
        if not (email and password):
            return None
    try:
        resp = httpx.post(f"{API_BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            if token:
                os.environ["WAP_TOKEN"] = token
                return token
    except Exception:
        pass
    return None


def _headers(token: Optional[str]) -> Dict[str, str]:
    h: Dict[str, str] = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _call(method: str, path: str, token: Optional[str] = None,
          params: Optional[Dict[str, Any]] = None,
          json_body: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
    """Perform the HTTP call; return (ok, data-or-error-message)."""
    try:
        resp = httpx.request(method, f"{API_BASE}{path}", headers=_headers(token),
                             params=params, json=json_body, timeout=TIMEOUT)
    except httpx.ConnectError:
        return False, (f"Server not reachable at {API_BASE}. "
                       f"Run: python cli.py start-server")
    except Exception as e:
        return False, f"Request failed: {e}"

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.json().get("error") or resp.text[:200]
        except Exception:
            detail = resp.text[:200]
        return False, f"HTTP {resp.status_code}: {detail}"
    try:
        return True, resp.json()
    except Exception:
        return True, resp.text


# ── Commands ──────────────────────────────────────────────────────────────────

import socket

def _is_port_in_use(port: int) -> bool:
    """Return True if the given port is already bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True

def cmd_toggle_subscription(client_id: int, status: bool, token: Optional[str] = None):
    """Turn a client's AI subscription on/off (admin).

    Off  -> customers get: "This business's AI assistant is temporarily
            offline. Please contact the business owner directly."
    """
    return _call("POST", f"/api/admin/clients/{client_id}/subscription",
                 token=token, json_body={"is_active": bool(status)})


def cmd_get_subscription(client_id: int, token: Optional[str] = None):
    return _call("GET", f"/api/admin/clients/{client_id}/subscription", token=token)


def cmd_start_server(port: int = 8000) -> Tuple[bool, str]:
    """Start the FastAPI backend (uvicorn) detached.
    If the port is already in use, assume the server is running and return success.
    """
    import time
    # Quick health check; if it works, server is up.
    try:
        httpx.get(f"http://127.0.0.1:{port}/health", timeout=3)
        return True, f"Server already running on port {port}"
    except Exception:
        pass
    # If port is bound but health check failed, avoid starting a new process.
    if _is_port_in_use(port):
        return True, f"Port {port} is in use; assuming server is running."
    log_out = open(AGENT_ENGINE / "cli_server.log", "ab")
    kwargs: Dict[str, Any] = dict(cwd=str(AGENT_ENGINE), stdout=log_out,
                                  stderr=subprocess.STDOUT)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app",
                      "--host", "127.0.0.1", "--port", str(port)], **kwargs)
    for _ in range(40):  # wait up to ~40s for the big app to boot
        time.sleep(1)
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
            return True, f"Server started on port {port}"
        except Exception:
            continue
    return False, f"Server did not come up on port {port} (see agent-engine/cli_server.log)"



def cmd_generate_report(client_id: int = 1, token: Optional[str] = None) -> Tuple[bool, Any]:
    token = token or get_token()
    if not token:
        return False, "No auth token. Set WAP_TOKEN or provide credentials."
    return _call("POST", "/weekly_report/generate", token=token,
                 params={"client_id": client_id})


def cmd_run_reengage(token: Optional[str] = None) -> Tuple[bool, Any]:
    token = token or get_token()
    if not token:
        return False, "No auth token. Set WAP_TOKEN or provide credentials."
    return _call("POST", "/reengagement/run", token=token, params={"client_id": 1})


def cmd_stop_reengage(lead_id: int, reason: str = "converted", token: Optional[str] = None) -> Tuple[bool, Any]:
    token = token or get_token()
    if not token:
        return False, "No auth token. Set WAP_TOKEN or provide credentials."
    return _call("POST", "/reengagement/stop", token=token, json_body={"lead_id": lead_id, "reason": reason})


def cmd_list_alerts(token: Optional[str] = None) -> Tuple[bool, Any]:
    return _call("GET", "/alerts", token=token)


def cmd_trigger_alerts(token: Optional[str] = None) -> Tuple[bool, Any]:
    return _call("POST", "/alerts/trigger", token=token, json_body={"name": "all"})


def cmd_approval_request(action_type: str, amount: Optional[float] = None,
                         payload: Optional[Dict[str, Any]] = None,
                         conversation_id: Optional[str] = None,
                         token: Optional[str] = None) -> Tuple[bool, Any]:
    body: Dict[str, Any] = {"action_type": action_type, "payload": payload or {}}
    if amount is not None:
        body["amount"] = amount
    if conversation_id:
        body["conversation_id"] = conversation_id
    return _call("POST", "/api/approval/request", token=token, json_body=body)


def cmd_approval_decision(request_id: str, approve: bool, comment: str = "",
                          token: Optional[str] = None) -> Tuple[bool, Any]:
    return _call("POST", f"/api/approvals/{request_id}/decide", token=token,
                 json_body={"decision": "approved" if approve else "rejected",
                            "comment": comment})


def cmd_pending_approvals(token: Optional[str] = None) -> Tuple[bool, Any]:
    return _call("GET", "/api/approvals/pending", token=token)


def load_payload_file(path: Optional[str]) -> Optional[Dict[str, Any]]:
    """Load a JSON payload file for approval-request."""
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Business setup (owner onboarding form)
# ---------------------------------------------------------------------------

BUSINESS_TYPES = ["restaurant", "hotel", "doctor", "ca", "lawyer", "salon",
                  "retail", "education", "general"]


def save_business_profile(payload: Dict[str, Any], token: Optional[str] = None) -> Tuple[bool, Any]:
    """Create/update the owner's business profile via POST /api/me/business."""
    return _call("POST", "/api/me/business", token=token, json_body=payload)


def add_catalog_item(item: Dict[str, Any], token: Optional[str] = None) -> Tuple[bool, Any]:
    """Add one catalog/menu item via POST /api/me/catalog/add."""
    return _call("POST", "/api/me/catalog/add", token=token, json_body=item)


def get_my_business(token: Optional[str] = None) -> Tuple[bool, Any]:
    """Fetch the owner's current business profile + catalog."""
    ok_b, biz = _call("GET", "/api/me/business", token=token)
    ok_c, cat = _call("GET", "/api/me/catalog", token=token)
    if not ok_b and not ok_c:
        return False, biz
    return True, {"business": biz if ok_b else None,
                  "catalog": (cat or {}).get("items", []) if ok_c else []}


def _ask(prompt: str, default: str = "", required: bool = False) -> str:
    val = ""
    while True:
        suffix = f" [{default}]" if default else ""
        val = input(f"  {prompt}{suffix}: ").strip()
        if not val and default:
            return default
        if val or not required:
            return val
        print("    * This field is required.")


def _ask_float(prompt: str, default: float) -> float:
    raw = _ask(prompt, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def cmd_manager_message(to_phone: str, instruction: str, send: bool,
                        token: Optional[str] = None) -> Tuple[bool, Any]:
    """Compose (and optionally send) a message AS the business manager,
    strictly from the business profile facts."""
    ok, resp = _call("POST", "/api/manager/message", token=token,
                     json_body={"to_phone": to_phone, "instruction": instruction,
                                "send": send})
    return ok, resp


def build_business_system_prompt(business: Optional[Dict[str, Any]] = None,
                                 catalog: Optional[List[Dict[str, Any]]] = None,
                                 owner_name: Optional[str] = None) -> str:
    """Build the 'speak-as-the-business' system prompt from a business profile.

    Fills system_prompt_template.txt with real business facts so every AI agent
    answers customers AS the business itself (real name, services, hours, ...).
    Falls back gracefully to a generic persona when no profile exists.

    Args:
        business: dict from GET /api/me/business (profile.to_dict()).
        catalog:  list of catalog items {'name': ...}.
        owner_name: owner's display name (from /auth/me), else falls back.
    """
    import pathlib
    b = business or {}
    items = catalog or []
    tmpl_path = pathlib.Path(__file__).resolve().parent / "agent-engine" / "system_prompt_template.txt"
    if not tmpl_path.exists():
        tmpl_path = pathlib.Path(__file__).resolve().parent / "system_prompt_template.txt"
    try:
        tmpl = tmpl_path.read_text(encoding="utf-8")
    except OSError:
        tmpl = "You are {business_name}, a {industry} based in {city}."

    # Services (sell-skill) -> prefer explicit 'services', else catalog names,
    # else description.
    services = b.get("services")
    if not isinstance(services, list) or not services:
        services = [i.get("name") for i in items if i.get("name")]
    if not services and b.get("description"):
        services = [b["description"]]
    services_lines = "\n".join(f"- {s}" for s in services) or "- (list your services via the business-setup form)"

    # Selling points -> explicit list, else derived from description/welcome.
    selling = b.get("selling_points")
    if not isinstance(selling, list) or not selling:
        selling = []
        if b.get("description"):
            selling.append(b["description"])
        if b.get("welcome_message"):
            selling.append(b["welcome_message"])
    selling_lines = "\n".join(f"- {s}" for s in selling) or "- (add selling points via the business-setup form)"

    # Location -> best-effort parse from address (city, region).
    address = (b.get("address") or "").strip()
    parts = [p.strip() for p in address.split(",") if p.strip()]
    city = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "your area")
    region = parts[-1] if len(parts) >= 2 else ""
    region_suffix = f" ({region})" if region else ""

    # Working hours -> {'summary': 'Mon-Sat 11-9'} or mapping.
    wh = b.get("working_hours") or {}
    if isinstance(wh, dict):
        working_hours = (wh.get("summary")
                         or ", ".join(f"{k}: {v}" for k, v in wh.items() if k != "summary"))
    elif isinstance(wh, str):
        working_hours = wh
    else:
        working_hours = ""
    if not working_hours:
        working_hours = "not specified"

    payment_methods = ", ".join(b.get("payment_methods") or []) or "cash / UPI"
    delivery = ("Yes" if b.get("delivery_enabled") else "No")
    if b.get("delivery_enabled") and b.get("delivery_radius_km"):
        delivery += f" within {b.get('delivery_radius_km')} km"

    return tmpl.format(
        business_name=b.get("name") or "our business",
        industry=b.get("business_type") or "local business",
        city=city,
        region_suffix=region_suffix,
        owner_name=owner_name or b.get("owner_name") or "the owner",
        contact_email=b.get("contact_email") or "(not set)",
        contact_phone=b.get("contact_phone") or "(not set)",
        services=services_lines,
        selling_points=selling_lines,
        working_hours=working_hours,
        payment_methods=payment_methods,
        delivery=delivery,
        welcome_message=b.get("welcome_message") or "Welcome!",
    )


def cmd_persona(token: Optional[str] = None) -> Tuple[bool, Any]:
    """Preview the 'speak-as-the-business' system prompt for the owner."""
    ok, data = get_my_business(token)
    if not ok:
        return False, data
    biz = (data or {}).get("business") or {}
    cat = (data or {}).get("catalog") or []
    if not biz:
        return False, "No business profile yet. Run: python cli.py business-setup"
    prompt = build_business_system_prompt(biz, catalog=cat)
    return True, prompt


def cmd_list_appointments(client_id: Optional[int] = None,
                          date: Optional[str] = None,
                          token: Optional[str] = None) -> Tuple[bool, Any]:
    """List appointments for a business (owner view, phones decrypted server-side)."""
    params: Dict[str, Any] = {}
    if client_id:
        params["client_id"] = client_id
    if date:
        params["date"] = date
    return _call("GET", "/api/appointments", token=token, params=params)


def cmd_create_appointment(phone: str, date: str, time: str,
                           client_id: int, title: str = "Appointment",
                           duration_minutes: int = 30,
                           token: Optional[str] = None) -> Tuple[bool, Any]:
    """Create an appointment via the API (same endpoint the AI slot-filler uses)."""
    return _call("POST", "/api/appointments", token=token, json_body={
        "phone_number": phone, "appointment_date": date,
        "appointment_time": time, "client_id": client_id,
        "title": title, "duration_minutes": duration_minutes,
    })


def cmd_business_client_id(token: Optional[str] = None) -> Optional[int]:
    """Resolve the logged-in owner's client_id (from /api/me/business)."""
    ok, data = get_my_business(token)
    if ok and isinstance(data, dict):
        biz = data.get("business") or data
        cid = biz.get("client_id") or biz.get("id")
        try:
            return int(cid)
        except (TypeError, ValueError):
            return None
    return None


def business_setup_interactive(token: Optional[str] = None) -> Tuple[bool, str]:
    """Guided CLI form: owner fills in all business details + menu.

    Saves via POST /api/me/business and /api/me/catalog/add so the AI agents
    answer customers with the real business facts (name, menu, hours, ...).
    """
    print("\n" + "=" * 62)
    print("  BUSINESS SETUP — tell the AI about your business")
    print("=" * 62)
    print("The chatbot's answers to customers come from these details,\n"
          "so fill in as much as you can. Press Enter to accept [defaults].\n")

    # 1. Identity
    print("— 1. Business identity " + "-" * 38)
    name = _ask("Business name (e.g. Tandoor House)", required=True)
    print(f"  Types: {', '.join(BUSINESS_TYPES)}")
    btype = _ask("Business type", "general").lower()
    if btype not in BUSINESS_TYPES:
        print("    * Unknown type, using 'general'")
        btype = "general"
    desc = _ask("Short description (what you do, specialties)")
    owner_phone = _ask("Owner WhatsApp number (e.g. 919876543210)")

    # 2. Contact & hours
    print("— 2. Contact & hours " + "-" * 41)
    contact_phone = _ask("Customer-facing phone", owner_phone)
    contact_email = _ask("Contact email")
    address = _ask("Address")
    website = _ask("Website (optional)")
    hours = _ask("Working hours (e.g. Mon-Sat 11:00-23:00)",
                 "Mon-Sun 09:00-21:00")

    # 3. Catalog / menu
    print("— 3. Menu / Catalog " + "-" * 43)
    print("  Add items/services one by one — the bot quotes prices from these.")
    items: list = []
    category_hint = {"restaurant": "Dishes", "doctor": "Services", "ca": "Services",
                     "lawyer": "Services", "salon": "Services", "hotel": "Rooms",
                     "education": "Courses"}.get(btype, "Products")
    while True:
        iname = _ask("Item name (leave blank to finish)", required=(len(items) == 0))
        if not iname:
            break
        icat = _ask("  Category", category_hint)
        iprice = _ask_float("  Price", 0.0)
        idesc = _ask("  Description (optional)")
        items.append({"name": iname, "category": icat, "price": iprice,
                      "description": idesc, "is_available": True})
        print(f"    + added '{iname}' ({len(items)} so far)\n")

    # 4. Commerce
    print("— 4. Payments & delivery " + "-" * 35)
    pay_raw = _ask("Payment methods (comma separated)", "cash, upi")
    payment_methods = [p.strip() for p in pay_raw.split(",") if p.strip()]
    delivery_enabled = _ask("Home delivery? (y/n)", "n").lower().startswith("y")
    delivery_radius = _ask_float("  Delivery radius (km)", 5.0) if delivery_enabled else 5
    tax = _ask_float("Tax rate %", 5.0)

    # 5. Brand
    print("— 5. Welcome message " + "-" * 41)
    default_welcome = f"Namaste! Welcome to {name}. How can I help you today?"
    welcome = _ask("Welcome message customers see first", default_welcome)

    payload = {
        "name": name,
        "business_type": btype,
        "description": desc,
        "welcome_message": welcome,
        "contact_phone": contact_phone,
        "contact_email": contact_email,
        "address": address,
        "website": website,
        "payment_methods": payment_methods,
        "delivery_enabled": delivery_enabled,
        "delivery_radius_km": delivery_radius,
        "tax_rate_percent": tax,
        "working_hours": {"summary": hours},
        "currency": "INR",
        "language": "hi_en",
    }

    ok, resp = save_business_profile(payload, token=token)
    if not ok:
        return False, (f"Failed to save business profile: {resp}\n"
                       f"Is the server running? try: python cli.py start-server")

    status = (resp or {}).get("status", "?") if isinstance(resp, dict) else "?"
    print(f"\n  [OK] Business profile {status}: '{name}'")

    added = 0
    if items:
        print(f"  ...adding {len(items)} catalog item(s)...")
        for it in items:
            ok_i, resp_i = add_catalog_item(it, token=token)
            if ok_i:
                added += 1
            else:
                print(f"    ! failed to add {it['name']}: {resp_i}")
        print(f"  [OK] {added}/{len(items)} catalog item(s) saved.")

    print("\n" + "=" * 62)
    print("  Done! The AI agents now know your business.")
    print("  Test it:  python wap-cli.py  ->  Chat Simulator")
    print("  or send a WhatsApp message to the connected number.")
    print("=" * 62)
    return True, f"Business '{name}' saved with {added} catalog item(s)."