"""
Auto-port allocation — Part J convenience layer.

Ensures backend (8000), bridge (3001/3002), worker and Chroma never collide
with a service already bound on the machine.  Simply asking the OS for an
ephemeral port and *not* using it is racy, so we bind a socket, read the
assigned port, and return it for the launcher to hand to the child.

One-click launcher flow (see launch_all.py) uses these helpers to pick ports
before spawning each process.
"""
from __future__ import annotations

import os
import socket
import time
from contextlib import closing
from typing import Dict, Optional, Tuple


def free_port(preferred: Optional[int] = None) -> int:
    """Return a usable TCP port.

    Tries *preferred* first; if it is taken (or None) an ephemeral free port is
    requested from the OS.  The returned port is free at the moment of the call.
    """
    if preferred is not None and not port_in_use(preferred):
        return preferred
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if something is already listening on (host, port)."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> bool:
    """Block until a TCP port accepts connections (i.e. a service is up)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_in_use(port, host):
            # Nothing listening yet; keep polling.
            time.sleep(0.1)
            continue
        try:
            with closing(socket.create_connection((host, port), timeout=0.4)):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def plan_ports(
    backend: int = 8000, bridge_http: int = 3001, bridge_ws: int = 3002,
    worker: int = 0, chroma: int = 8001,
) -> Dict[str, int]:
    """Compute non-colliding ports for the full service stack.

    ``worker`` 0 means "give me an ephemeral port" because the ARQ worker does
    not normally expose an HTTP port.
    """
    backend_p = free_port(backend)
    bridge_http_p = free_port(bridge_http)
    bridge_ws_p = free_port(bridge_ws)
    chroma_p = free_port(chroma)
    worker_p = free_port(worker) if worker else free_port()
    return {
        "backend": backend_p,
        "bridge_http": bridge_http_p,
        "bridge_ws": bridge_ws_p,
        "worker": worker_p,
        "chroma": chroma_p,
    }


def export_env(ports: Dict[str, int], prefix: str = "WAP_") -> Dict[str, str]:
    """Turn a port plan into environment variables for child processes."""
    mapping = {
        "backend": "PORT",
        "bridge_http": "BRIDGE_HTTP_PORT",
        "bridge_ws": "BRIDGE_WS_PORT",
        "chroma": "CHROMA_PORT",
    }
    env = {}
    for key, var in mapping.items():
        if key in ports:
            env[var] = str(ports[key])
    env[f"{prefix}PLAN"] = ",".join(f"{k}={v}" for k, v in ports.items())
    return env