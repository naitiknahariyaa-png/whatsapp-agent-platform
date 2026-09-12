"""
CLI functional registry - expose ANY platform function on the terminal.

Every new functional (feature/function) is added here in ONE line and is
then immediately runnable from the CLI without touching cli.py:

    python cli.py functional                        # list everything
    python cli.py functional accounts.list          # run with no args
    python cli.py functional accounts.setup --args "{\"path\": \"p.json\"}"

To add a new functional: call register(name, help, module, attr, params)
at the bottom of this file (module.attr is imported lazily, so heavy
modules only load when actually used).
"""
from __future__ import annotations

import asyncio
import importlib
from typing import Any, Dict, Optional

REGISTRY: Dict[str, Dict[str, Any]] = {}


def register(name: str, help: str, module: str, attr: str,
             params: Optional[Dict[str, Any]] = None) -> None:
    """Register module.attr as a terminal-runnable functional."""
    REGISTRY[name] = {"name": name, "help": help, "module": module,
                      "attr": attr, "params": params or {}}


def list_functional() -> list:
    return sorted(REGISTRY.values(), key=lambda r: r["name"])


def run_functional(name: str, kwargs: Optional[Dict[str, Any]] = None) -> Any:
    """Import module.attr lazily and run it (async functions supported)."""
    spec = REGISTRY.get(name)
    if not spec:
        raise KeyError("unknown functional: " + name)
    fn = getattr(importlib.import_module(spec["module"]), spec["attr"])
    kwargs = kwargs or {}
    if asyncio.iscoroutinefunction(fn):
        return asyncio.run(fn(**kwargs))
    return fn(**kwargs)


# ---- small composition wrappers (keep registration one-liners simple) ----
def _report_build(path: str, brand_voice: str = "casual") -> list:
    from report_broadcast import build_all, load_report
    return build_all(load_report(path), brand_voice=brand_voice)


def _creative_plan(path: str, voice: str = "casual", limit: int = 0) -> list:
    from report_broadcast import load_report, normalize_phone
    from creative_broadcast import plan_creative_batch
    contacts = []
    for r in load_report(path):
        ph = normalize_phone(r.get("phone", ""))
        if ph:
            contacts.append({"first_name": r.get("first_name")
                             or r.get("name") or "", "phone": ph, "tags": {}})
    if limit:
        contacts = contacts[:limit]
    profile = {"business_name": "Your Business", "vertical": "general",
               "brand_voice": voice,
               "service_name": "AI-Powered Booking Assistant"}
    return plan_creative_batch(contacts, profile, rotate="alternate")


# ---- registered functionals (ONE line each - add new features here) ----
register("accounts.list", "List all business accounts",
         "multi_accounts", "list_accounts")
register("accounts.setup", "Create accounts from a profiles JSON",
         "multi_accounts", "setup_accounts",
         {"path": "samples/profiles.sample.json"})
register("accounts.run", "Run ALL accounts in parallel (AI per account)",
         "multi_accounts", "run_all",
         {"mode": "simulate", "limit": 0, "fast": True})
register("broadcast.copy", "Per-account outreach copy from profile + contact",
         "multi_accounts", "build_account_message",
         {"profile": {"business_name": "My Shop", "vertical": "retail"},
          "contact": {"name": "Ramesh", "phone": "+919999999999"}})
register("report.load", "Load a contacts report (xlsx/csv)",
         "report_broadcast", "load_report", {"path": "contacts.xlsx"})
register("report.build", "Build outreach messages from a report",
         "cli_registry", "_report_build",
         {"path": "contacts.xlsx", "brand_voice": "casual"})
register("creative.plan", "Plan A/B creative broadcast from a report",
         "cli_registry", "_creative_plan",
         {"path": "contacts.xlsx", "voice": "casual", "limit": 0})
register("prompt.build", "Build the anti-hallucination system prompt "
         "from a profile JSON", "prompt_builder", "build_system_prompt",
         {"profile": {"business_name": "My Salon", "brand_voice": "casual",
                      "menu": [{"name": "Haircut", "price": 299}]}})
register("prompt.build-client", "Build the system prompt for a client id",
         "prompt_builder", "build_system_prompt_for_client", {"client_id": 1})
