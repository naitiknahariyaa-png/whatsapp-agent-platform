"""
Analytics Agent - Part D worker roster.

Answers owner-facing reporting questions ("how did this week go?", "where are
leads dropping off?") with REAL numbers pulled from the analytics event store
and the platform database.  Deterministic by design: money-adjacent reporting
must never hallucinate, so run() computes figures directly instead of relying
on an LLM free-form answer.  The LLM layer is only used to phrase the summary
when available, with a plain-text fallback that is still correct.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from agents.base import BaseAgent
from model_router import get_simple_qa_llm

logger = logging.getLogger("analytics_agent")


class AnalyticsAgent(BaseAgent):
    """The Data Analyst: funnel, response-time and growth reporting."""

    def __init__(self):
        system_prompt = (
            "You are the Business Analyst. You report REAL numbers only. "
            "\n\nRULES:\n"
            "1. Never invent metrics — restate the numbers you are given verbatim.\n"
            "2. Lead with the headline trend, then one concrete recommendation.\n"
            "3. If a metric is missing, say it is unavailable; do not estimate.\n"
            "4. Keep reports under 120 words; owners read them on WhatsApp."
        )
        super().__init__(
            name="DataSensei",
            role="Analytics & Reporting",
            system_prompt=system_prompt,
            tools=[],           # reads data directly; no dispatcher tools needed
        )
        # Cheap model is enough for phrasing a summary of computed numbers.
        self.llm = get_simple_qa_llm()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def run(self, user_input: str, context: Dict[str, Any] = None) -> str:
        context = context or {}
        client_id = int(context.get("client_id", 1))
        metrics = await self.collect_metrics(client_id)

        if not metrics.get("available"):
            return (
                "I could not gather analytics right now. "
                "Please try again shortly — if this keeps happening the "
                "owner can check /api/diagnostic for component health."
            )

        summary = self._rule_summary(metrics)
        phrased = await self._phrase(summary)
        return phrased or summary

    async def collect_metrics(self, client_id: int) -> Dict[str, Any]:
        """Gather real funnel + volume numbers. Never raises."""
        metrics: Dict[str, Any] = {"available": False}
        try:
            from utils.analytics import funnel_dropoff_report
            funnel = await funnel_dropoff_report(client_id)
            metrics["funnel"] = funnel
            metrics["available"] = True
        except Exception as exc:          # pragma: no cover - defensive
            logger.warning("funnel report unavailable for %s: %s", client_id, exc)

        try:
            from db import async_session, Message, Contact, Appointment
            from sqlalchemy import select, func
            async with async_session() as session:
                metrics["total_messages"] = (await session.execute(
                    select(func.count()).select_from(Message)
                    .where(Message.client_id == client_id))).scalar() or 0
                metrics["total_contacts"] = (await session.execute(
                    select(func.count()).select_from(Contact)
                    .where(Contact.client_id == client_id))).scalar() or 0
                metrics["total_appointments"] = (await session.execute(
                    select(func.count()).select_from(Appointment)
                    .where(Appointment.client_id == client_id))).scalar() or 0
                contacts = metrics["total_contacts"]
                metrics["conversion_rate"] = round(
                    metrics["total_appointments"] / contacts * 100, 1
                ) if contacts else 0.0
                metrics["available"] = True
        except Exception as exc:          # pragma: no cover - defensive
            logger.warning("volume stats unavailable for %s: %s", client_id, exc)

        return metrics

    # ------------------------------------------------------------------
    # Summarisation
    # ------------------------------------------------------------------
    def _rule_summary(self, m: Dict[str, Any]) -> str:
        """Deterministic plain-text report from real metrics."""
        lines = ["📊 Business snapshot:"]

        if "total_messages" in m:
            lines.append(
                f"• {m['total_messages']} messages exchanged with "
                f"{m['total_contacts']} contacts"
            )
        if "total_appointments" in m:
            conv = m.get("conversion_rate", 0.0)
            lines.append(
                f"• {m['total_appointments']} appointments booked "
                f"({conv}% of contacts converted)"
            )

        funnel = m.get("funnel")
        worst = self._worst_funnel_stage(funnel)
        if worst:
            name, dropoff = worst
            lines.append(f"• Biggest drop-off: {name} ({dropoff} lost)")

        lines.append(self._recommendation(m))
        return "\n".join(lines)

    @staticmethod
    def _worst_funnel_stage(funnel: Any):
        """Return (stage_name, dropoff) for the largest loss, if any."""
        try:
            stages = funnel.stages if hasattr(funnel, "stages") else funnel
            best = None
            for s in stages or []:
                drop = getattr(s, "dropoff", None)
                if drop is None and isinstance(s, dict):
                    drop = s.get("dropoff")
                name = getattr(s, "name", None) or (
                    s.get("name") if isinstance(s, dict) else None)
                if name is None or drop is None:
                    continue
                if best is None or drop > best[1]:
                    best = (str(name), int(drop))
            return best
        except Exception:                 # pragma: no cover - defensive
            return None

    @staticmethod
    def _recommendation(m: Dict[str, Any]) -> str:
        conv = m.get("conversion_rate")
        contacts = m.get("total_contacts", 0)
        if conv is not None and contacts >= 10 and conv < 20:
            return ("💡 Advice: conversion is under 20% — tighten your "
                    "welcome message and follow up leads within an hour.")
        if m.get("total_messages", 0) > 100 and contacts < 20:
            return ("💡 Advice: few contacts generate many messages — "
                    "consider a VIP segment for your regulars.")
        return "💡 Advice: metrics look healthy; keep monitoring response times."

    async def _phrase(self, summary: str) -> str:
        """Optional LLM polish. Falls back to the rule-based text on failure."""
        try:
            res = await self.llm.ainvoke([
                {"role": "system", "content": (
                    "Rewrite this business report warmly in under 80 words. "
                    "Keep every number EXACTLY as given.")},
                {"role": "user", "content": summary},
            ])
            content = getattr(res, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
        except Exception as exc:          # pragma: no cover - defensive
            logger.debug("analytics phrasing skipped: %s", exc)
        return ""

