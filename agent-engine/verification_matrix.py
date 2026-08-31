"""
Verification Matrix — Part L.

A single source of truth that maps every platform capability to its validation
layer: unit → integration → end-to-end → load → chaos.  Used by CI to confirm
the whole stack is validated and by the QA checklist to see coverage gaps.

The matrix is data, not fancy logic.  Commit a row per capability.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any

LAYERS = ["unit", "integration", "e2e", "load", "chaos"]

VERIFICATION_MATRIX: List[Dict[str, Any]] = [
    # (capability, owner area, the test files/functions that cover it, per-layer status)
    {
        "capability": "Onboarding & multi-tenant owner creation",
        "area": "Part B",
        "tests": ["tests/test_onboarding.py", "tests/test_multitenancy.py", "tests/test_tenant_isolation.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Cross-tenant data isolation",
        "area": "Part B",
        "tests": ["tests/test_tenant_isolation.py", "tests/test_multitenancy.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Webhook HMAC signature verification",
        "area": "Part A",
        "tests": ["tests/test_security.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Timestamp-windowed replay protection",
        "area": "Part A",
        "tests": ["tests/test_security.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Anti-ban messaging (delay, cooldown, opt-out, daily cap)",
        "area": "Part A",
        "tests": ["tests/test_security.py", "tests/test_messaging.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Durable task queue (ARQ worker)",
        "area": "Part A",
        "tests": ["tests/test_framework_health.py", "tests/arq_worker.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Bridge watchdog (2-failure restart)",
        "area": "Part A",
        "tests": ["whatsapp_connector.py"],
        "layers": {"unit": False, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Central event bus (Pub/Sub)",
        "area": "Part H",
        "tests": ["tests/test_reliability_parts.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Idempotent side-effect execution",
        "area": "Part G",
        "tests": ["tests/test_reliability_parts.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Alert quiet-hours routing",
        "area": "Part H",
        "tests": ["tests/test_reliability_parts.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Constraint extraction (Hinglish eval set)",
        "area": "Part E",
        "tests": ["tests/test_constraint_extraction_eval.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Manager Agent + worker registry",
        "area": "Part C",
        "tests": ["tests/test_orchestrator.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Growth loops (lead funnel, nurture, re-engagement)",
        "area": "Part F",
        "tests": ["tests/test_loops.py"],
        "layers": {"unit": True, "integration": False, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Owner WebSocket real-time dashboard fan-out",
        "area": "Part H",
        "tests": ["main.py:websocket_notifications"],
        "layers": {"unit": False, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Analytics Agent (real-number reporting)",
        "area": "Part D",
        "tests": ["tests/test_part_d_analytics_agent.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Redis cache with explicit invalidation",
        "area": "Part A",
        "tests": ["tests/test_part_a_cache.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "QA surfacing (logs + health summary)",
        "area": "Part K",
        "tests": ["tests/test_part_k_wiring.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Retention agent wiring (re-engagement loop UI)",
        "area": "Part K",
        "tests": ["tests/test_part_k_wiring.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Human approval gate (refunds, pending, decide)",
        "area": "Part K",
        "tests": ["tests/test_part_k_wiring.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
    {
        "capability": "Advisory history persistence",
        "area": "Part K",
        "tests": ["tests/test_part_k_wiring.py"],
        "layers": {"unit": True, "integration": True, "e2e": False, "load": False, "chaos": False},
    },
]


def filter_matrix(area: Optional[str] = None, layer: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return matrix rows matching an area and/or a layer flag being set."""
    out = []
    for row in VERIFICATION_MATRIX:
        if area and row["area"].lower() != area.lower():
            continue
        if layer and not row["layers"].get(layer, False):
            continue
        out.append(row)
    return out


def coverage_report() -> Dict[str, Any]:
    """Summarise layer coverage across all capabilities."""
    report: Dict[str, Dict[str, int]] = {}
    total = len(VERIFICATION_MATRIX)
    for layer in LAYERS:
        covered = sum(1 for r in VERIFICATION_MATRIX if r["layers"].get(layer))
        report[layer] = {"covered": covered, "total": total, "pct": round(100.0 * covered / total, 1) if total else 0}
    return report


def matrix_summary() -> Dict[str, Any]:
    """Full human- and CI-readable summary."""
    return {
        "rows": len(VERIFICATION_MATRIX),
        "layers": LAYERS,
        "coverage": coverage_report(),
        "areas": sorted({r["area"] for r in VERIFICATION_MATRIX}),
    }