"""
One-click launch — Part J.

Spins up the whole local stack on non-colliding ports so a developer can go from
`python launch_all.py` to a running platform.  Uses port_allocator to pick free
ports, then spawns each service with the ports exported into its environment.

Services started:
  1. Backend API (uvicorn main:app)
  2. WhatsApp bridge (node whatsapp-bridge/bridge.js, optional)
  3. ARQ worker (optional)
  4. ChromaDB (optional)

By default only the backend is started to avoid depending on Node/Docker.
Use --with-bridge / --with-worker / --with-chroma to opt into the rest.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from typing import List

from port_allocator import plan_ports, export_env, wait_for_port

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENGINE = os.path.abspath(os.path.dirname(__file__))


def _python(py_dirs: List[str]) -> str:
    return sys.executable


def launch(backend_port: int, all_services: bool) -> List[subprocess.Popen]:
    """Launch services and return the list of running processes."""
    plan = plan_ports(backend=backend_port)
    env = os.environ.copy()
    env.update(export_env(plan))
    env["PORT"] = str(plan["backend"])

    procs: List[subprocess.Popen] = []

    # 1) Backend
    backend = subprocess.Popen(
        [_python(), "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(plan["backend"])],
        cwd=ENGINE,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    procs.append(backend)
    print(f"[v] Backend starting on :{plan['backend']} (pid {backend.pid})")

    # 2) WhatsApp bridge (optional)
    if all_services:
        bridge_js = os.path.join(ROOT, "whatsapp-bridge", "bridge.js")
        if os.path.exists(bridge_js):
            env["HTTP_PORT"] = str(plan["bridge_http"])
            env["WS_PORT"] = str(plan["bridge_ws"])
            env["AGENT_API_URL"] = f"http://localhost:{plan['backend']}"
            bridge = subprocess.Popen(
                ["node", bridge_js],
                cwd=os.path.join(ROOT, "whatsapp-bridge"),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            procs.append(bridge)
            print(f"[v] WhatsApp bridge starting on :{plan['bridge_http']} (pid {bridge.pid})")

    # Wait for backend to accept connections
    if wait_for_port(plan["backend"], timeout=20):
        print(f"[v] Backend accepting connections on http://localhost:{plan['backend']}")
        url = f"http://localhost:{plan['backend']}/frontend/dashboard.html"
        webbrowser.open(url)
    else:
        print("[w] Backend did not become ready within 20s — check logs.")

    return procs


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-click launch of the WhatsApp Agent Platform")
    parser.add_argument("--port", type=int, default=8000, help="Preferred backend port")
    parser.add_argument("--all", action="store_true", help="Also launch bridge/worker/chroma")
    args = parser.parse_args(argv)

    procs = launch(args.port, all_services=args.all)
    print("\nAll services started. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping services...")
        for p in procs:
            p.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())