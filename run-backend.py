#!/usr/bin/env python3
"""
WhatsApp Agent Platform — Backend Runner (NO FRONTEND)
Runs FastAPI API server only. Terminal CLI connects to this.
"""
import os
import sys

# Ensure agent-engine is in path
ROOT = os.path.abspath(os.path.dirname(__file__))
AGENT_ENGINE = os.path.join(ROOT, "agent-engine")
SERVICES = os.path.join(ROOT, "services")

for p in [AGENT_ENGINE, SERVICES]:
    if p not in sys.path:
        sys.path.insert(0, p)

os.chdir(AGENT_ENGINE)

# Set terminal mode BEFORE importing main
os.environ.setdefault("WAP_TERMINAL_MODE", "1")

from main import app
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"[i] Starting WAP Backend on {host}:{port}")
    print("[i] Frontend: DISABLED (terminal only)")
    uvicorn.run(app, host=host, port=port, log_level="info")
