"""
Reporting Module - Generates CRM summaries and monthly reports with CA insights.
Uses LLM (Groq) to generate narrative insights from structured data.
"""
import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import select, func, text

from db import get_session, Message, Contact, Appointment, Conversation
from lead_gen import Lead
from llm_setup import get_llm

logger = logging.getLogger("reporting")


class ReportGenerator:
    """Generates CRM summaries and monthly reports."""

    def __init__(self):
        self.llm = get_llm()

    async def _query_stats(self, client_id: int, month: str = None) -> Dict:
        """Query database for CRM statistics."""
        stats = {
            "total_conversations": 0,
            "total_messages": 0,
            "incoming_messages": 0,
            "outgoing_messages": 0,
            "total_contacts": 0,
            "total_leads": 0,
            "qualified_leads": 0,
            "converted_leads": 0,
            "total_appointments": 0,
            "scheduled_appointments": 0,
            "completed_appointments": 0,
            "cancelled_appointments": 0,
            "top_intents": {},
            "sentiment_summary": {"positive": 0, "neutral": 0, "negative": 0},
        }

        try:
            async for session in get_session():
                # Total conversations
                result = await session.execute(
                    select(func.count()).select_from(Conversation).where(Conversation.client_id == client_id)
                )
                stats["total_conversations"] = result.scalar() or 0

                # Total messages
                result = await session.execute(
                    select(func.count()).select_from(Message).where(Message.client_id == client_id)
                )
                stats["total_messages"] = result.scalar() or 0

                # Incoming/outgoing messages
                result = await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.client_id == client_id, Message.direction == "incoming"
                    )
                )
                stats["incoming_messages"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.client_id == client_id, Message.direction == "outgoing"
                    )
                )
                stats["outgoing_messages"] = result.scalar() or 0

                # Contacts
                result = await session.execute(
                    select(func.count()).select_from(Contact).where(Contact.client_id == client_id)
                )
                stats["total_contacts"] = result.scalar() or 0

                # Leads
                result = await session.execute(
                    select(func.count()).select_from(Lead).where(Lead.client_id == client_id)
                )
                stats["total_leads"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count()).select_from(Lead).where(
                        Lead.client_id == client_id, Lead.status.in_(["qualified", "converted"])
                    )
                )
                stats["qualified_leads"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count()).select_from(Lead).where(
                        Lead.client_id == client_id, Lead.status == "converted"
                    )
                )
                stats["converted_leads"] = result.scalar() or 0

                # Appointments
                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(Appointment.client_id == client_id)
                )
                stats["total_appointments"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id, Appointment.status == "scheduled"
                    )
                )
                stats["scheduled_appointments"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id, Appointment.status == "completed"
                    )
                )
                stats["completed_appointments"] = result.scalar() or 0

                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id, Appointment.status == "cancelled"
                    )
                )
                stats["cancelled_appointments"] = result.scalar() or 0

        except Exception as e:
            logger.error(f"Failed to query stats: {e}")

        return stats

    async def generate_monthly_report(self, client_id: int, month: str = None) -> Dict:
        """
        Generate a monthly CRM report with CA insights.
        month format: YYYY-MM (defaults to current month)
        """
        if not month:
            month = datetime.now(timezone.utc).strftime("%Y-%m")

        stats = await self._query_stats(client_id, month)

        # Generate narrative insights using LLM
        narrative = await self._generate_narrative(stats, month)

        report = {
            "client_id": client_id,
            "month": month,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
            "narrative": narrative,
            "ca_insights": self._generate_ca_insights(stats),
        }
        return report

    async def _generate_narrative(self, stats: Dict, month: str) -> str:
        """Generate narrative summary using LLM."""
        try:
            if not hasattr(self.llm, 'invoke'):
                return "LLM not available for narrative generation."

            prompt = f"""You are a business intelligence analyst for a WhatsApp-based business.
Generate a concise monthly performance summary based on these stats for {month}:

- Total conversations: {stats['total_conversations']}
- Total messages: {stats['total_messages']} (incoming: {stats['incoming_messages']}, outgoing: {stats['outgoing_messages']})
- Total contacts: {stats['total_contacts']}
- Total leads: {stats['total_leads']} (qualified: {stats['qualified_leads']}, converted: {stats['converted_leads']})
- Total appointments: {stats['total_appointments']} (scheduled: {stats['scheduled_appointments']}, completed: {stats['completed_appointments']}, cancelled: {stats['cancelled_appointments']})

Write a 3-4 sentence summary highlighting:
1. Overall performance
2. Key strengths
3. Areas needing improvement
4. Recommended next actions

Keep it professional and actionable."""

            response = await asyncio.to_thread(self.llm.invoke, prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Narrative generation failed: {e}")
            return "Unable to generate narrative summary."

    def _generate_ca_insights(self, stats: Dict) -> Dict:
        """Generate CA-specific insights from the stats."""
        conversion_rate = 0
        if stats["total_leads"] > 0:
            conversion_rate = round((stats["converted_leads"] / stats["total_leads"]) * 100, 1)

        appointment_rate = 0
        if stats["total_appointments"] > 0:
            appointment_rate = round((stats["completed_appointments"] / stats["total_appointments"]) * 100, 1)

        return {
            "lead_conversion_rate": f"{conversion_rate}%",
            "appointment_completion_rate": f"{appointment_rate}%",
            "engagement_ratio": f"{stats['incoming_messages']}/{stats['outgoing_messages']}",
            "estimated_revenue_potential": self._estimate_revenue(stats),
            "follow_up_needed": stats["qualified_leads"] - stats["converted_leads"],
            "recommendations": [
                "Follow up with qualified leads not yet converted",
                "Review cancelled appointments for scheduling issues",
                "Increase engagement with inactive contacts",
            ],
        }

    def _estimate_revenue(self, stats: Dict) -> str:
        """Estimate revenue potential based on converted leads."""
        # Simple heuristic: assume avg ₹5000 per converted lead
        estimated = stats["converted_leads"] * 5000
        return f"₹{estimated:,} (estimated, based on avg ₹5,000/lead)"


# Global instance
report_generator = ReportGenerator()