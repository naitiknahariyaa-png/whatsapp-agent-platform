"""
WhatsApp Connector - Manages the WhatsApp bridge lifecycle
Starts/stops the bridge process and serves QR codes through the API
"""
import os
import sys
import json
import time
import subprocess
import threading
import asyncio
from pathlib import Path
from typing import Optional, Dict

# Bridge location
BRIDGE_DIR = Path(__file__).parent.parent / "whatsapp-bridge"
BRIDGE_SCRIPT = BRIDGE_DIR / "bridge.js"
BRIDGE_HTTP_PORT = int(os.getenv("BRIDGE_HTTP_PORT", "3001"))
BRIDGE_WS_PORT = int(os.getenv("BRIDGE_WS_PORT", "3002"))

class WhatsAppConnector:
    """Manages the WhatsApp bridge process and connection state"""
    
    def __init__(self):
        self.bridge_process: Optional[subprocess.Popen] = None
        self.bridge_started_at: Optional[float] = None
        self._lock = threading.Lock()
        self._last_qr: Optional[str] = None
        self._connected: bool = False
        self._connection_info: Dict = {}
        self._start_attempts = 0
        
    @property
    def is_running(self) -> bool:
        """Check if bridge process is running"""
        if self.bridge_process is None:
            return False
        return self.bridge_process.poll() is None
    
    @property
    def is_connected(self) -> bool:
        """Check if WhatsApp is connected"""
        return self._connected
    
    def start_bridge(self) -> Dict:
        """Start the WhatsApp bridge process"""
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
                    timeout=5
                )
                if node_check.returncode != 0:
                    return {"status": "error", "message": "Node.js is not installed. Please install Node.js to connect WhatsApp."}
                
                # Check if dependencies are installed
                node_modules = BRIDGE_DIR / "node_modules"
                if not node_modules.exists():
                    return {
                        "status": "error",
                        "message": "Bridge dependencies not installed. Run: cd whatsapp-bridge && npm install"
                    }
                
                # Start the bridge process
                env = os.environ.copy()
                env["HTTP_PORT"] = str(BRIDGE_HTTP_PORT)
                env["WS_PORT"] = str(BRIDGE_WS_PORT)
                env["AGENT_API_URL"] = f"http://localhost:{os.getenv('PORT', '8000')}"
                
                self.bridge_process = subprocess.Popen(
                    ["node", str(BRIDGE_SCRIPT)],
                    cwd=str(BRIDGE_DIR),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
                self.bridge_started_at = time.time()
                self._start_attempts += 1
                
                # Start monitoring thread
                threading.Thread(target=self._monitor_bridge, daemon=True).start()
                
                return {
                    "status": "started",
                    "message": "WhatsApp bridge started. Waiting for QR code...",
                    "pid": self.bridge_process.pid
                }
                
            except Exception as e:
                return {"status": "error", "message": f"Failed to start bridge: {str(e)}"}
    
    def _monitor_bridge(self):
        """Monitor bridge output for QR codes and connection status"""
        if not self.bridge_process or not self.bridge_process.stdout:
            return
        
        try:
            for line in self.bridge_process.stdout:
                line = line.strip()
                if not line:
                    continue
                
                # Look for QR code in output
                if "SCAN THIS QR CODE" in line or "QR" in line:
                    # QR will be in subsequent lines
                    pass
                
                # Check for connection
                if "WhatsApp connected" in line or "ready" in line.lower():
                    self._connected = True
                    print(f"[WhatsAppConnector] Connected: {line}")
                
                if "authenticated" in line.lower():
                    self._connected = True
                    print(f"[WhatsAppConnector] Authenticated: {line}")
                
                if "auth_failure" in line.lower() or "failed" in line.lower():
                    self._connected = False
                    print(f"[WhatsAppConnector] Auth failure: {line}")
                    
        except Exception as e:
            print(f"[WhatsAppConnector] Monitor error: {e}")
    
    def stop_bridge(self) -> Dict:
        """Stop the bridge process"""
        with self._lock:
            if self.bridge_process and self.is_running:
                self.bridge_process.terminate()
                try:
                    self.bridge_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.bridge_process.kill()
                self.bridge_process = None
                self._connected = False
                return {"status": "stopped", "message": "Bridge stopped"}
            return {"status": "not_running", "message": "Bridge is not running"}
    
    def get_status(self) -> Dict:
        """Get current bridge status"""
        import httpx
        
        # Check if bridge HTTP is responding
        bridge_online = False
        try:
            resp = httpx.get(f"http://localhost:{BRIDGE_HTTP_PORT}/health", timeout=3)
            if resp.status_code == 200:
                bridge_online = True
                data = resp.json()
                self._connected = data.get("whatsapp") != "disconnected"
                self._connection_info = data.get("whatsapp", {}) if isinstance(data.get("whatsapp"), dict) else {}
        except Exception:
            bridge_online = False
        
        return {
            "bridge_running": self.is_running or bridge_online,
            "bridge_online": bridge_online,
            "connected": self._connected,
            "connection_info": self._connection_info,
            "bridge_port": BRIDGE_HTTP_PORT,
            "started_at": self.bridge_started_at
        }
    
    def get_qr(self) -> Dict:
        """Get QR code from the bridge"""
        import httpx
        
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
                        "message": "Scan QR with WhatsApp to connect"
                    }
                elif data.get("status") == "waiting":
                    return {"status": "waiting", "qr": None, "message": "Waiting for QR code..."}
            return {"status": "unavailable", "qr": None, "message": "Bridge not responding"}
        except Exception as e:
            return {"status": "offline", "qr": None, "message": f"Bridge offline: {str(e)}"}


# Global connector instance
whatsapp_connector = WhatsAppConnector()