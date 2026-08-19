#!/usr/bin/env python3
"""
WhatsApp Agent Platform — Terminal Control Panel
No website. Pure terminal. Full control.
"""

import os
import sys
import json
import asyncio
import subprocess
import threading
import httpx
from pathlib import Path
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.resolve()
AGENT_ENGINE = ROOT / "agent-engine"
WHATSAPP_BRIDGE = ROOT / "whatsapp-bridge"
BRIDGE_SCRIPT = WHATSAPP_BRIDGE / "bridge.js"
BRIDGE_HTTP_PORT = int(os.getenv("BRIDGE_HTTP_PORT", "3001"))
BRIDGE_WS_PORT = int(os.getenv("BRIDGE_WS_PORT", "3002"))
API_PORT = int(os.getenv("PORT", "8000"))

# Add agent-engine to path
sys.path.insert(0, str(AGENT_ENGINE))
sys.path.insert(0, str(ROOT / "services"))

# ── Colors (ANSI) ────────────────────────────────────────────────────────────
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"


def cprint(text, color=""):
    if color:
        print(f"{color}{text}{C.RESET}")
    else:
        print(text)


def banner(text):
    print(f"\n{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{text.center(60)}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 60}{C.RESET}\n")


def success(text):
    cprint(f"  {C.GREEN}✓{C.RESET} {text}")


def error(text):
    cprint(f"  {C.RED}✗{C.RESET} {text}")


def warn(text):
    cprint(f"  {C.YELLOW}!{C.RESET} {text}")


def info(text):
    cprint(f"  {C.BLUE}i{C.RESET} {text}")


def hr():
    print(f"{C.DIM}{'-' * 60}{C.RESET}")


# ── Backend imports ──────────────────────────────────────────────────────────
_backend_loaded = False

def load_backend():
    global _backend_loaded
    if _backend_loaded:
        return True
    try:
        import db  # noqa: F401
        _backend_loaded = True
        return True
    except Exception as e:
        error(f"Failed to load backend: {e}")
        return False


# ── Bridge Manager ───────────────────────────────────────────────────────────
class BridgeManager:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self._connected = False
        self._connection_state = "disconnected"
        self._phone_number: str | None = None
        self._connection_info: dict = {}

    @property
    def is_running(self) -> bool:
        if self.process is None:
            return False
        return self.process.poll() is None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> dict:
        if self.is_running:
            return {"status": "already_running"}

        if not BRIDGE_SCRIPT.exists():
            return {"status": "error", "message": f"Bridge script not found at {BRIDGE_SCRIPT}"}

        try:
            node_check = subprocess.run(
                ["node", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if node_check.returncode != 0:
                return {"status": "error", "message": "Node.js not installed"}

            node_modules = WHATSAPP_BRIDGE / "node_modules"
            if not node_modules.exists():
                return {"status": "error", "message": "Bridge deps missing. Run: cd whatsapp-bridge && npm install"}

            env = os.environ.copy()
            env["HTTP_PORT"] = str(BRIDGE_HTTP_PORT)
            env["WS_PORT"] = str(BRIDGE_WS_PORT)
            env["MAX_MEMORY_MB"] = os.getenv("MAX_MEMORY_MB", "256")
            env["AGENT_API_URL"] = f"http://localhost:{API_PORT}"

            self.process = subprocess.Popen(
                ["node", str(BRIDGE_SCRIPT)],
                cwd=str(WHATSAPP_BRIDGE),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            threading.Thread(target=self._monitor, daemon=True).start()
            return {"status": "started", "pid": self.process.pid, "port": BRIDGE_HTTP_PORT}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def stop(self) -> dict:
        if self.process and self.is_running:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
            self._connected = False
            self._connection_state = "disconnected"
            return {"status": "stopped"}
        return {"status": "not_running"}

    def _monitor(self):
        if not self.process or not self.process.stdout:
            return
        try:
            for line in self.process.stdout:
                line = line.strip()
                if not line:
                    continue
                if "WhatsApp connected" in line or "ready" in line.lower():
                    self._connected = True
                    self._connection_state = "connected"
                    print(f"{C.GREEN}[Bridge] Connected{C.RESET}")
                elif "authenticated" in line.lower():
                    self._connected = True
                    self._connection_state = "authenticated"
                    print(f"{C.GREEN}[Bridge] Authenticated{C.RESET}")
                elif "auth_failure" in line.lower() or "failed" in line.lower():
                    self._connected = False
                    self._connection_state = "failed"
                    print(f"{C.RED}[Bridge] Auth failure{C.RESET}")
                elif "disconnected" in line.lower():
                    self._connected = False
                    self._connection_state = "disconnected"
                    print(f"{C.YELLOW}[Bridge] Disconnected{C.RESET}")
        except Exception:
            pass

    def get_status(self) -> dict:
        bridge_online = False
        try:
            resp = httpx.get(f"http://localhost:{BRIDGE_HTTP_PORT}/health", timeout=3)
            if resp.status_code == 200:
                bridge_online = True
                data = resp.json()
                self._connected = data.get("connected", False)
                self._connection_state = data.get("connection_state", "disconnected")
                wa = data.get("whatsapp", {})
                if isinstance(wa, dict):
                    self._connection_info = wa
                    self._phone_number = wa.get("number")
        except Exception:
            bridge_online = False
            self._connected = False
            self._connection_state = "offline"

        return {
            "bridge_running": self.is_running or bridge_online,
            "bridge_online": bridge_online,
            "connected": self._connected,
            "connection_state": self._connection_state,
            "phone_number": self._phone_number,
            "connection_info": self._connection_info,
        }

    def get_qr(self) -> dict:
        try:
            resp = httpx.get(f"http://localhost:{BRIDGE_HTTP_PORT}/qr", timeout=5)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "unavailable"}
        except Exception as e:
            return {"status": "offline", "error": str(e)}

    def send_message(self, to: str, message: str) -> dict:
        try:
            resp = httpx.post(
                f"http://localhost:{BRIDGE_HTTP_PORT}/send",
                json={"to": to, "message": message},
                timeout=15,
            )
            return resp.json() if resp.status_code == 200 else {"status": "error", "message": resp.text}
        except Exception as e:
            return {"status": "offline", "error": str(e)}


bridge = BridgeManager()
_backend_process: subprocess.Popen | None = None


def start_backend() -> dict:
    global _backend_process
    if _backend_process and _backend_process.poll() is None:
        return {"status": "already_running"}

    # Check if already running externally
    try:
        resp = httpx.get(f"http://localhost:{API_PORT}/health", timeout=2)
        if resp.status_code == 200:
            return {"status": "already_running", "message": "Backend already running on port " + str(API_PORT)}
    except Exception:
        pass

    try:
        env = os.environ.copy()
        env["WAP_TERMINAL_MODE"] = "1"
        env["PORT"] = str(API_PORT)
        env["HOST"] = "127.0.0.1"

        _backend_process = subprocess.Popen(
            [sys.executable, str(ROOT / "run-backend.py")],
            cwd=str(ROOT),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        # Wait for it to start
        for _ in range(20):
            time.sleep(0.5)
            try:
                resp = httpx.get(f"http://localhost:{API_PORT}/health", timeout=2)
                if resp.status_code == 200:
                    return {"status": "started", "pid": _backend_process.pid, "port": API_PORT}
            except Exception:
                continue

        return {"status": "error", "message": "Backend started but not responding"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def stop_backend() -> dict:
    global _backend_process
    if _backend_process and _backend_process.poll() is None:
        _backend_process.terminate()
        try:
            _backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _backend_process.kill()
        _backend_process = None
        return {"status": "stopped"}
    return {"status": "not_running"}


def is_backend_running() -> bool:
    try:
        resp = httpx.get(f"http://localhost:{API_PORT}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


# ── Backend helpers ──────────────────────────────────────────────────────────
async def get_llm_status():
    from llm_setup import get_provider_status
    return get_provider_status()


async def list_leads(status: str = ""):
    from lead_gen import lead_gen_agent
    return await lead_gen_agent.get_leads(status)


async def create_lead(phone: str, name: str = "", source: str = "direct"):
    from lead_gen import lead_gen_agent
    return await lead_gen_agent.create_lead(phone_number=phone, name=name, source=source)


async def update_lead_status(lead_id: int, status: str):
    from lead_gen import lead_gen_agent
    return await lead_gen_agent.update_lead_status(lead_id, status)


async def list_appointments(client_id: int = 1, date: str = ""):
    from db import async_session, Appointment
    from sqlalchemy import select
    async with async_session() as session:
        q = select(Appointment).where(Appointment.client_id == client_id)
        if date:
            q = q.where(Appointment.appointment_date == date)
        result = await session.execute(q.order_by(Appointment.appointment_date.desc()))
        appts = result.scalars().all()
        return [{
            "id": a.id,
            "phone": a.phone_number,
            "title": a.title,
            "date": a.appointment_date,
            "time": a.appointment_time,
            "status": a.status,
        } for a in appts]


async def create_appointment(phone: str, title: str, date: str, time: str, client_id: int = 1):
    from db import async_session, Appointment
    appt = Appointment(
        client_id=client_id,
        phone_number=phone,
        title=title,
        appointment_date=date,
        appointment_time=time,
        status="scheduled",
    )
    async with async_session() as session:
        session.add(appt)
        await session.commit()
        await session.refresh(appt)
        return {"id": appt.id, "status": "created"}


async def list_campaigns():
    from drip_campaigns import engine
    return [c.to_dict() for c in engine.campaigns.values()]


async def create_campaign(name: str, description: str = ""):
    from drip_campaigns import DripCampaign, engine
    import hashlib
    campaign_id = hashlib.md5(f"{name}_{datetime.utcnow().timestamp()}".encode()).hexdigest()[:12]
    campaign = DripCampaign(id=campaign_id, name=name, description=description)
    engine.register_campaign(campaign)
    return campaign.to_dict()


async def enroll_contact(campaign_id: str, contact_id: str, channel: str = "whatsapp"):
    from drip_campaigns import engine
    key = await engine.enroll(campaign_id, contact_id, channel)
    return {"key": key}


async def process_message_direct(phone: str, message: str, client_id: int = 1) -> str:
    orch = await get_orchestrator()
    return await orch.process_message(phone, message, client_id)


# ── Terminal UI ───────────────────────────────────────────────────────────────
def show_dashboard():
    banner("SYSTEM DASHBOARD")
    hr()

    backend_ok = load_backend()
    cprint(f"Backend Modules:  {'Loaded' if backend_ok else 'Failed'}", C.GREEN if backend_ok else C.RED)

    status = bridge.get_status()
    state = status["connection_state"]
    state_color = {"connected": C.GREEN, "authenticated": C.GREEN, "connecting": C.YELLOW, "qr": C.YELLOW, "disconnected": C.RED, "failed": C.RED, "offline": C.RED}.get(state, "")
    cprint(f"WhatsApp Bridge:  {state}", state_color)
    if status.get("phone_number"):
        cprint(f"  Phone:          {status['phone_number']}")

    try:
        llm_status = asyncio.run(get_llm_status())
        active = [k for k, v in llm_status.items() if v.get("available")]
        provider = active[0] if active else "mock"
        cprint(f"LLM Provider:     {provider}", C.GREEN if provider != "mock" else C.YELLOW)
    except Exception:
        cprint("LLM Provider:     Error", C.RED)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        leads = loop.run_until_complete(list_leads())
        appts = loop.run_until_complete(list_appointments())
        campaigns = loop.run_until_complete(list_campaigns())
        loop.close()

        cprint(f"Leads:            {len(leads)}")
        cprint(f"Appointments:     {len(appts)}")
        cprint(f"Campaigns:        {len(campaigns)}")
    except Exception as e:
        cprint(f"DB Stats:         Error: {e}", C.RED)

    hr()


def show_bridge_menu():
    while True:
        banner("WHATSAPP BRIDGE")
        hr()
        status = bridge.get_status()
        state = status["connection_state"]
        state_color = {"connected": C.GREEN, "authenticated": C.GREEN, "connecting": C.YELLOW, "qr": C.YELLOW, "disconnected": C.RED, "failed": C.RED, "offline": C.RED}.get(state, "")
        cprint(f"Status: {state}", state_color)
        if status.get("phone_number"):
            cprint(f"Number: {status['phone_number']}")
        hr()

        print(f"  {C.CYAN}1{C.RESET}. Start Bridge")
        print(f"  {C.CYAN}2{C.RESET}. Stop Bridge")
        print(f"  {C.CYAN}3{C.RESET}. Show QR Code")
        print(f"  {C.CYAN}4{C.RESET}. Refresh QR")
        print(f"  {C.CYAN}5{C.RESET}. Connection Progress")
        print(f"  {C.CYAN}6{C.RESET}. Send Test Message")
        print(f"  {C.CYAN}0{C.RESET}. Back")
        hr()

        choice = input(f"{C.BOLD}Select: {C.RESET}").strip()

        if choice == "1":
            print("Starting bridge...")
            result = bridge.start()
            if result.get("status") == "started":
                success(f"Bridge started (PID: {result.get('pid')}, Port: {result.get('port')})")
                info("Waiting for QR code... Open WhatsApp and scan.")
            else:
                error(result.get("message", "Failed to start"))

        elif choice == "2":
            result = bridge.stop()
            success(result.get("message", "Bridge stopped"))

        elif choice == "3":
            qr = bridge.get_qr()
            if qr.get("qr"):
                info("QR Code received")
                try:
                    import qrcode
                    qr_obj = qrcode.QRCode(border=2, box_size=1)
                    qr_obj.add_data(qr["qr"])
                    qr_obj.make(fit=True)
                    qr_obj.print_ascii(invert=True)
                except Exception:
                    cprint(f"QR Data: {qr['qr']}")
            else:
                warn(qr.get("message", "No QR available"))

        elif choice == "4":
            result = bridge.get_qr()
            if result.get("status") == "ready" and result.get("qr"):
                info("QR refreshed. Scan with WhatsApp.")
            else:
                warn("No QR available. Start bridge first.")

        elif choice == "5":
            progress = bridge.get_status()
            cprint(json.dumps(progress, indent=2))

        elif choice == "6":
            to = input("Phone number (with country code): ").strip() or "919876543210"
            msg = input("Message: ").strip() or "Hello from WAP Terminal!"
            result = bridge.send_message(to, msg)
            if result.get("status") == "sent":
                success(f"Message sent! WAMID: {result.get('wamid', 'N/A')}")
            else:
                error(f"Send failed: {result}")

        elif choice == "0":
            break

        input("\nPress Enter to continue...")


def show_chat_menu():
    banner("CHAT SIMULATOR")
    hr()
    info("Simulate WhatsApp conversations locally")
    hr()

    phone = input("Customer phone: ").strip() or "919876543210"
    client_id = int(input("Client ID: ").strip() or "1")

    print(f"\nType messages and see AI responses. Type 'quit' to exit.\n")

    while True:
        try:
            msg = input(f"{C.CYAN}Customer:{C.RESET} ").strip()
            if msg.lower() in ("quit", "exit", "q"):
                break
            if not msg:
                continue

            print(f"{C.YELLOW}AI thinking...{C.RESET}", end="\r")
            response = asyncio.run(process_message_direct(phone, msg, client_id))
            print(f"{' ' * 30}\r", end="")  # Clear thinking line

            cprint(f"{C.GREEN}Bot:{C.RESET} {response}")
            hr()
        except KeyboardInterrupt:
            break
        except Exception as e:
            error(str(e))


def show_leads_menu():
    while True:
        banner("LEAD CRM")
        hr()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            leads = loop.run_until_complete(list_leads())
            loop.close()
        except Exception as e:
            error(f"Failed to load leads: {e}")
            leads = []

        print(f"Leads ({len(leads)}):")
        for l in leads:
            print(f"  {l['id']}: {l['phone']} | {l['name'] or '-'} | Score: {l['score']} | {l['status']} | {l['source'] or '-'}")

        hr()
        print(f"  {C.CYAN}1{C.RESET}. Create Lead")
        print(f"  {C.CYAN}2{C.RESET}. Update Lead Status")
        print(f"  {C.CYAN}3{C.RESET}. View Lead Detail")
        print(f"  {C.CYAN}4{C.RESET}. Refresh")
        print(f"  {C.CYAN}0{C.RESET}. Back")
        hr()

        choice = input(f"{C.BOLD}Select: {C.RESET}").strip()

        if choice == "1":
            phone = input("Phone: ").strip() or "919876543210"
            name = input("Name: ").strip()
            source = input("Source: ").strip() or "terminal"
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            lead = loop.run_until_complete(create_lead(phone, name, source))
            loop.close()
            success(f"Lead created: ID {lead.get('id', '?')}")

        elif choice == "2":
            lead_id = int(input("Lead ID: ").strip())
            status = input("Status (new/qualified/contacted/converted/lost): ").strip()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(update_lead_status(lead_id, status))
            loop.close()
            success(str(result))

        elif choice == "3":
            from lead_gen import lead_gen_agent
            lead_id = int(input("Lead ID: ").strip())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            detail = loop.run_until_complete(lead_gen_agent.get_lead_detail(lead_id))
            loop.close()
            if detail:
                cprint(json.dumps(detail, indent=2))
            else:
                warn("Lead not found")

        elif choice == "0":
            break

        input("\nPress Enter to continue...")


def show_appointments_menu():
    while True:
        banner("APPOINTMENTS")
        hr()

        date = input("Filter by date (YYYY-MM-DD, empty=all): ").strip()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            appts = loop.run_until_complete(list_appointments(date=date) if date else list_appointments())
            loop.close()
        except Exception as e:
            error(f"Failed: {e}")
            appts = []

        for a in appts:
            print(f"  {a['id']}: {a['phone']} | {a['title'] or '-'} | {a['date'] or '-'} {a['time'] or '-'} | {a['status']}")

        hr()
        print(f"  {C.CYAN}1{C.RESET}. Create Appointment")
        print(f"  {C.CYAN}2{C.RESET}. Refresh")
        print(f"  {C.CYAN}0{C.RESET}. Back")
        hr()

        choice = input(f"{C.BOLD}Select: {C.RESET}").strip()

        if choice == "1":
            phone = input("Phone: ").strip() or "919876543210"
            title = input("Title: ").strip() or "Consultation"
            date = input("Date (YYYY-MM-DD): ").strip()
            time = input("Time (HH:MM): ").strip() or "10:00"
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(create_appointment(phone, title, date, time))
            loop.close()
            success(f"Appointment created: ID {result.get('id')}")

        elif choice == "0":
            break

        input("\nPress Enter to continue...")


def show_campaigns_menu():
    while True:
        banner("DRIP CAMPAIGNS")
        hr()

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            campaigns = loop.run_until_complete(list_campaigns())
            loop.close()
        except Exception as e:
            error(f"Failed: {e}")
            campaigns = []

        print(f"Campaigns ({len(campaigns)}):")
        for c in campaigns:
            active = "Active" if c["is_active"] else "Inactive"
            print(f"  {c['id']}: {c['name']} | {c['trigger']} | {active}")

        hr()
        print(f"  {C.CYAN}1{C.RESET}. Create Campaign")
        print(f"  {C.CYAN}2{C.RESET}. Enroll Contact in Campaign")
        print(f"  {C.CYAN}3{C.RESET}. View Campaign Stats")
        print(f"  {C.CYAN}4{C.RESET}. Refresh")
        print(f"  {C.CYAN}0{C.RESET}. Back")
        hr()

        choice = input(f"{C.BOLD}Select: {C.RESET}").strip()

        if choice == "1":
            name = input("Campaign name: ").strip()
            desc = input("Description: ").strip()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            campaign = loop.run_until_complete(create_campaign(name, desc))
            loop.close()
            success(f"Campaign created: {campaign['id']} - {campaign['name']}")

        elif choice == "2":
            campaign_id = input("Campaign ID: ").strip()
            contact_id = input("Contact ID / Phone: ").strip()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(enroll_contact(campaign_id, contact_id))
            loop.close()
            success(f"Enrolled: {result.get('key')}")

        elif choice == "3":
            from drip_campaigns import engine
            campaign_id = input("Campaign ID: ").strip()
            stats = engine.get_campaign_stats(campaign_id)
            cprint(json.dumps(stats, indent=2))

        elif choice == "0":
            break

        input("\nPress Enter to continue...")


def show_llm_menu():
    banner("LLM SETTINGS")
    hr()

    try:
        llm_status = asyncio.run(get_llm_status())
        print("LLM Providers:")
        for name, info in llm_status.items():
            avail = "Available" if info.get("available") else "Unavailable"
            err = info.get("error", "-") or "-"
            print(f"  {name}: {avail} | {err}")
    except Exception as e:
        error(f"Failed to get LLM status: {e}")

    hr()
    info("Providers: groq -> ollama -> openai -> mock")
    info("Set env vars: GROQ_API_KEY, OLLAMA_BASE_URL, OPENAI_API_KEY")
    info("Or edit agent-engine/.env")


def show_diagnostics():
    banner("DIAGNOSTICS")
    hr()

    checks = []

    checks.append(("Python", f"{sys.version.split()[0]}"))

    try:
        nv = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
        checks.append(("Node.js", nv))
    except Exception:
        checks.append(("Node.js", "Not found"))

    backend_ok = load_backend()
    checks.append(("Backend Modules", "Loaded" if backend_ok else "Failed"))

    checks.append(("Bridge Script", "Found" if BRIDGE_SCRIPT.exists() else "Missing"))
    checks.append(("Bridge Node Modules", "Found" if (WHATSAPP_BRIDGE / "node_modules").exists() else "Missing"))

    try:
        from db import engine as db_engine
        checks.append(("Database", "Connected"))
    except Exception as e:
        checks.append(("Database", f"Error: {e}"))

    try:
        llm_status = asyncio.run(get_llm_status())
        active = [k for k, v in llm_status.items() if v.get("available")]
        provider = active[0] if active else "mock"
        checks.append(("LLM Provider", provider))
    except Exception:
        checks.append(("LLM Provider", "Error"))

    try:
        resp = httpx.get(f"http://localhost:{API_PORT}/health", timeout=3)
        checks.append(("API Server", f"Running (port {API_PORT})" if resp.status_code == 200 else f"HTTP {resp.status_code}"))
    except Exception:
        checks.append(("API Server", f"Not reachable on port {API_PORT}"))

    if bridge.is_running:
        checks.append(("Bridge Process", f"Running (PID: {bridge.process.pid})"))
    else:
        checks.append(("Bridge Process", "Not running"))

    print("System Diagnostics:")
    for comp, stat in checks:
        print(f"  {comp}: {stat}")

    hr()


def show_send_menu():
    banner("SEND MESSAGE")
    hr()

    to = input("To (phone with country code): ").strip() or "919876543210"
    msg = input("Message: ").strip() or "Hello from WAP Terminal!"

    info("Sending via WhatsApp bridge...")
    result = bridge.send_message(to, msg)
    if result.get("status") == "sent":
        success(f"Sent! WAMID: {result.get('wamid', 'N/A')}")
    else:
        error(f"Failed: {result}")


# ── Main Menu ────────────────────────────────────────────────────────────────
def ensure_backend():
    if not is_backend_running():
        warn("Backend API not running. Starting...")
        result = start_backend()
        if result.get("status") == "started":
            success(f"Backend started (PID: {result.get('pid')}, Port: {result.get('port')})")
        else:
            error(f"Failed to start backend: {result.get('message')}")
            return False
    return True


def main_menu():
    banner("WHATSAPP AGENT PLATFORM — TERMINAL CONTROL")
    hr()
    cprint("No website. Pure terminal. Full power.\n", C.DIM)

    # Ensure backend is running
    if not is_backend_running():
        warn("Backend API not detected. Starting automatically...")
        result = start_backend()
        if result.get("status") == "started":
            success(f"Backend started (PID: {result.get('pid')})")
        else:
            error(f"Auto-start failed: {result.get('message')}")
            cprint("You can still manage bridge and use chat simulator locally.", C.YELLOW)

    while True:
        print(f"  {C.CYAN}1{C.RESET}. Dashboard")
        print(f"  {C.CYAN}2{C.RESET}. WhatsApp Bridge")
        print(f"  {C.CYAN}3{C.RESET}. Chat Simulator")
        print(f"  {C.CYAN}4{C.RESET}. Lead CRM")
        print(f"  {C.CYAN}5{C.RESET}. Appointments")
        print(f"  {C.CYAN}6{C.RESET}. Drip Campaigns")
        print(f"  {C.CYAN}7{C.RESET}. LLM Settings")
        print(f"  {C.CYAN}8{C.RESET}. Send Message")
        print(f"  {C.CYAN}9{C.RESET}. Diagnostics")
        print(f"  {C.CYAN}0{C.RESET}. Exit")
        hr()

        choice = input(f"{C.BOLD}Select: {C.RESET}").strip()

        if choice == "1":
            show_dashboard()
        elif choice == "2":
            show_bridge_menu()
        elif choice == "3":
            show_chat_menu()
        elif choice == "4":
            show_leads_menu()
        elif choice == "5":
            show_appointments_menu()
        elif choice == "6":
            show_campaigns_menu()
        elif choice == "7":
            show_llm_menu()
        elif choice == "8":
            show_send_menu()
        elif choice == "9":
            show_diagnostics()
        elif choice == "0":
            cprint("\nGoodbye! 👋", C.GREEN)
            sys.exit(0)

        input("\nPress Enter to continue...")


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        cprint("\n\nGoodbye! 👋", C.GREEN)
        sys.exit(0)
