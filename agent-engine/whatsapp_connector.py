"""
WhatsApp Connector - Manages the WhatsApp bridge lifecycle
Starts/stops the bridge process and serves QR codes through the API.

Supports:
- Automated phone verification (via bridge /connect endpoints)
- Session persistence and reconnection (LocalAuth in .wwebjs_auth)
- Real-time connection status tracking (via /health, /status, and WebSocket)
- One-click connection using verification codes (Meta Cloud API path)
"""
import os
import sys
import json
import time
import subprocess
import threading
import asyncio
import httpx
from pathlib import Path
from typing import Optional, Dict

# Bridge location
BRIDGE_DIR = Path(__file__).parent.parent / "whatsapp-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"
BRIDGE_HTTP_PORT = int(os.getenv("BRIDGE_HTTP_PORT", "3001"))
BRIDGE_WS_PORT = int(os.getenv("BRIDGE_WS_PORT", "3002"))


class WhatsAppConnector:
    """Manages the WhatsApp bridge process and connection state."""

    def __init__(self):
        self.bridge_process: Optional[subprocess.Popen] = None
        self.bridge_started_at: Optional[float] = None
        self._lock = threading.Lock()
        self._last_qr: Optional[str] = None
        self._connected: bool = False
        self._connection_info: Dict = {}
        self._start_attempts = 0
        self._connection_state: str = "disconnected"
        self._phone_number: Optional[str] = None  # for automated verification

    @property
    def is_running(self) -> bool:
        """Check if bridge process is running."""
        if self.bridge_process is None:
            return False
        return self.bridge_process.poll() is None

    @property
    def is_connected(self) -> bool:
        """Check if WhatsApp is connected."""
        return self._connected

    def start_bridge(self) -> Dict:
        """Start the WhatsApp bridge process."""
        with self._lock:
            if self.is_running:
                return {"status": "already_running", "message": "Bridge is already running"}

            if not BRIDGE_SCRIPT.exists():
                return {"status": "error", "message": f"Bridge script not found at {BRIDGE_SCRIPT}"}

            try:
                # Check if node is available
                node_check = subprocess.run(
                    ["node", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if node_check.returncode != 0:
                    return {"status": "error", "message": "Node.js is not installed. Please install Node.js to connect WhatsApp."}

                # Check if dependencies are installed
                node_modules = BRIDGE_DIR / "node_modules"
                if not node_modules.exists():
                    return {
                        "status": "error",
                        "message": "Bridge dependencies not installed. Run: cd whatsapp-bridge && npm install",
                    }

                # Start the bridge process
                env = os.environ.copy()
                env["HTTP_PORT"] = str(BRIDGE_HTTP_PORT)
                env["WS_PORT"] = str(BRIDGE_WS_PORT)
                env["MAX_MEMORY_MB"] = os.getenv("MAX_MEMORY_MB", "256")
                env["AGENT_API_URL"] = f"http://localhost:{os.getenv('PORT', '8000')}"

                self.bridge_process = subprocess.Popen(
                    ["node", str(BRIDGE_SCRIPT)],
                    cwd=str(BRIDGE_DIR),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                self.bridge_started_at = time.time()
                self._start_attempts += 1

                # Start monitoring thread
                threading.Thread(target=self._monitor_bridge, daemon=True).start()

                return {
                    "status": "started",
                    "message": "WhatsApp bridge started. Waiting for QR code...",
                    "pid": self.bridge_process.pid,
                    "bridge_port": BRIDGE_HTTP_PORT,
                }

            except Exception as e:
                return {"status": "error", "message": f"Failed to start bridge: {str(e)}"}

    def _monitor_bridge(self):
        """Monitor bridge output for QR codes and connection status."""
        if not self.bridge_process or not self.bridge_process.stdout:
            return

        try:
            for line in self.bridge_process.stdout:
                line = line.strip()
                if not line:
                    continue

                # Check for connection
                if "WhatsApp connected" in line or "ready" in line.lower():
                    self._connected = True
                    self._connection_state = "connected"
                    print(f"[WhatsAppConnector] Connected: {line}")

                if "authenticated" in line.lower():
                    self._connected = True
                    self._connection_state = "authenticated"
                    print(f"[WhatsAppConnector] Authenticated: {line}")

                if "auth_failure" in line.lower() or "failed" in line.lower():
                    self._connected = False
                    self._connection_state = "failed"
                    print(f"[WhatsAppConnector] Auth failure: {line}")

                if "disconnected" in line.lower():
                    self._connected = False
                    self._connection_state = "disconnected"
                    print(f"[WhatsAppConnector] Disconnected: {line}")

        except Exception as e:
            print(f"[WhatsAppConnector] Monitor error: {e}")

    def stop_bridge(self) -> Dict:
        """Stop the bridge process."""
        with self._lock:
            if self.bridge_process and self.is_running:
                self.bridge_process.terminate()
                try:
                    self.bridge_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.bridge_process.kill()
                self.bridge_process = None
                self._connected = False
                self._connection_state = "disconnected"
                return {"status": "stopped", "message": "Bridge stopped"}
            return {"status": "not_running", "message": "Bridge is not running"}

    def get_status(self) -> Dict:
        """Get current bridge status."""
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
                else:
                    self._connection_info = {}
        except Exception:
            bridge_online = False
            self._connected = False
            self._connection_state = "offline"

        return {
            "bridge_running": self.is_running or bridge_online,
            "bridge_online": bridge_online,
            "connected": self._connected,
            "connection_state": self._connection_state,
            "connection_info": self._connection_info,
            "phone_number": self._phone_number,
            "bridge_port": BRIDGE_HTTP_PORT,
            "started_at": self.bridge_started_at,
            "start_attempts": self._start_attempts,
        }

    def get_qr(self) -> Dict:
        """Get QR code from the bridge."""
        try:
            resp = httpx.get(f"http://localhost:{BRIDGE_HTTP_PORT}/qr", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("qr"):
                    self._last_qr = data["qr"]
                    return {
                        "status": "ready",
                        "qr": data["qr"],
                        "data_url": data.get("data_url"),
                        "message": "Scan QR with WhatsApp to connect",
                    }
                elif data.get("status") == "waiting":
                    return {"status": "waiting", "qr": None, "message": "Waiting for QR code..."}
                elif data.get("status") == "connected":
                    return {"status": "connected", "qr": None, "message": "Already connected"}
            return {"status": "unavailable", "qr": None, "message": "Bridge not responding"}
        except Exception as e:
            return {"status": "offline", "qr": None, "message": f"Bridge offline: {str(e)}"}

    def request_verification_code(self, phone_number: str, method: str = "sms") -> Dict:
        """
        Request a verification code for the given phone number via the bridge.
        For the local bridge (whatsapp-web.js), this triggers QR generation.
        For Meta Cloud API, this would use the official verification flow.
        """
        try:
            resp = httpx.post(
                f"http://localhost:{BRIDGE_HTTP_PORT}/connect/request-code",
                json={"phone_number": phone_number, "method": method},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._phone_number = phone_number
                return data
            return {"status": "error", "message": f"Bridge returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"status": "offline", "message": f"Bridge offline: {str(e)}"}

    def submit_verification_code(self, phone_number: str, code: str, method: str = "sms") -> Dict:
        """
        Submit a verification code to complete WhatsApp connection.
        For the local bridge, this is informational (QR-based auth is used).
        For Meta Cloud API, the code completes phone verification.
        """
        try:
            resp = httpx.post(
                f"http://localhost:{BRIDGE_HTTP_PORT}/connect/verify",
                json={"phone_number": phone_number, "code": code, "method": method},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data
            return {"status": "error", "message": f"Bridge returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"status": "offline", "message": f"Bridge offline: {str(e)}"}

    def send_message(self, to: str, message: str) -> Dict:
        try:
            resp = httpx.post(f"http://localhost:{BRIDGE_HTTP_PORT}/send", json={"to": to, "message": message}, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "message": f"Bridge returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"status": "offline", "message": f"Bridge offline: {str(e)}"}

    def broadcast(self, contacts: list, message: str) -> Dict:
        try:
            resp = httpx.post(f"http://localhost:{BRIDGE_HTTP_PORT}/broadcast", json={"contacts": contacts, "message": message}, timeout=120)
            if resp.status_code == 200:
                return resp.json()
            return {"status": "error", "message": f"Bridge returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"status": "offline", "message": f"Bridge offline: {str(e)}"}

    def get_connection_progress(self) -> Dict:
        """
        Get real-time connection progress for automated phone verification.
        Returns the current state, QR code (if available), and phone number.
        """
        status = self.get_status()
        qr_data = self.get_qr() if not status["connected"] else {"status": "connected", "qr": None}
        return {
            "phone_number": self._phone_number,
            "connection_state": status.get("connection_state", "disconnected"),
            "connected": status.get("connected", False),
            "qr": qr_data.get("qr"),
            "qr_data_url": qr_data.get("data_url"),
            "connection_info": status.get("connection_info", {}),
            "message": self._get_state_message(status.get("connection_state", "disconnected")),
        }

    def automated_connect(self, phone_number: str, method: str = "sms") -> Dict:
        """
        Fully automated phone number verification without QR scanning.

        Starts the bridge (if not running), requests a verification code,
        and tracks connection progress in real time.
        
        For the local bridge (whatsapp-web.js), this triggers QR generation
        with session persistence via .wwebjs_auth (LocalAuth).
        
        For Meta Cloud API (via bridge), this uses the official verification flow.
        """
        # Ensure bridge is running
        if not self.is_running:
            start_result = self.start_bridge()
            if start_result.get("status") == "error":
                return start_result

        # Request verification code / QR
        code_result = self.request_verification_code(phone_number, method)
        status = self.get_status()

        return {
            "phone_number": phone_number,
            "bridge_started": True,
            "verification_requested": True,
            "connection_state": status.get("connection_state", "connecting"),
            "connected": status.get("connected", False),
            "qr": self.get_qr().get("qr"),
            "qr_data_url": self.get_qr().get("data_url"),
            "message": self._get_state_message(status.get("connection_state", "connecting")),
            "next_steps": [
                "If QR is available: Scan with WhatsApp Business app",
                "If code requested (SMS/Voice): Check your phone for the code and call submit_verification_code()",
                "Connection state is tracked in real-time via get_status()",
            ],
        }

    def connect_with_code(self, phone_number: str, code: str, method: str = "sms") -> Dict:
        """
        One-click WhatsApp connection using a verification code.
        
        Submits the code received via SMS or voice call to complete
        the automated phone verification process.
        """
        result = self.submit_verification_code(phone_number, code, method)
        status = self.get_status()

        # Poll for a few seconds to confirm connection
        for _ in range(5):
            if status.get("connected"):
                break
            import time as _time
            _time.sleep(1)
            status = self.get_status()

        result["connected"] = status.get("connected", False)
        result["connection_state"] = status.get("connection_state", "unknown")
        return result

    def verify_code(self, phone_number: str, code: str, method: str = "sms") -> Dict:
        """
        Verify a WhatsApp verification code and confirm connection.
        
        Alias for connect_with_code with additional status polling.
        """
        result = self.connect_with_code(phone_number, code, method)
        if result.get("connected"):
            result["message"] = "WhatsApp verification successful � account connected!"
        else:
            result["message"] = "Verification submitted. Check status with get_status()."
        return result

    def _get_state_message(self, state: str) -> str:
        """Human-readable message for a connection state."""
        messages = {
            "disconnected": "Bridge is not connected. Click 'Start Bridge' to begin.",
            "connecting": "Connecting to WhatsApp...",
            "qr": "Scan the QR code with your WhatsApp app to connect.",
            "authenticated": "Session verified. Finalizing connection...",
            "connected": "WhatsApp is connected and ready!",
            "failed": "Connection failed. Check your credentials and try again.",
            "offline": "Bridge is offline. Waiting for bridge to start...",
        }
        return messages.get(state, "Status unknown")


# Global connector instance
whatsapp_connector = WhatsAppConnector()
