"""
Tool Registry - Production-grade tool registration and execution
"""
import json
import logging
import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("tool_registry")


@dataclass
class Tool:
    """Definition of a callable tool for the LLM."""
    name: str
    description: str
    parameters: Dict[str, Any]
    callable: Callable
    requires_confirmation: bool = False


class ToolRegistry:
    """Central registry for agent tools with async execution support."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool
        logger.info("Tool %r registered (requires_confirmation=%s)", tool.name, tool.requires_confirmation)

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_openai_function_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return schemas

    async def execute(self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any] = None) -> Dict[str, Any]:
        tool = self._tools.get(tool_name)
        if not tool:
            return {"error": f"Tool '{tool_name}' not found.", "status": "error"}

        if tool.requires_confirmation:
            return {
                "status": "pending_confirmation",
                "tool": tool_name,
                "arguments": arguments,
                "message": f"This action requires confirmation: {tool.description}",
            }

        try:
            result = await tool.callable(**arguments)
            return {
                "status": "success",
                "tool": tool_name,
                "result": result,
            }
        except TypeError as e:
            logger.error("Tool %s argument error: %s", tool_name, e)
            return {"status": "error", "tool": tool_name, "error": f"Invalid arguments: {e}"}
        except Exception as e:
            logger.error("Tool %s execution error: %s", tool_name, e)
            return {"status": "error", "tool": tool_name, "error": str(e)}


# ---------------------------------------------------------------------------
# Built-in tool implementations
# ---------------------------------------------------------------------------

async def _check_calendar(date: str, duration_minutes: int = 30, client_id: int = 1):
    from tools.calendar_tools import check_calendar as _check
    return await _check(date)


async def _create_appointment(phone_number: str, date: str, time: str, title: str, client_id: int = 1):
    from tools.calendar_tools import book_appointment as _book
    result = await _book(phone_number, date, time, title)
    if isinstance(result, str) and ("Successfully" in result or "booked" in result.lower()):
        from db import async_session, Appointment, upsert_contact
        async with async_session() as session:
            appt = Appointment(
                client_id=client_id,
                phone_number=phone_number,
                appointment_date=date,
                appointment_time=time,
                title=title,
                duration_minutes=duration_minutes if 'duration_minutes' in dir() else 30,
                status="scheduled",
            )
            session.add(appt)
            await session.commit()
            await session.refresh(appt)
            await upsert_contact(session, phone_number, client_id=client_id)
            return {
                "appointment_id": appt.id,
                "phone_number": phone_number,
                "date": date,
                "time": time,
                "title": title,
                "status": "scheduled",
            }
    return {"error": result}


async def _lookup_product(query: str, client_id: int = 1):
    from vector_store import search_knowledge
    results = search_knowledge(client_id, query, n_results=5)
    if not results:
        return {"results": [], "message": "No products found matching your query."}
    return {"results": results}


async def _send_email(to: str, subject: str, body: str, client_id: int = 1):
    from email_auth import email_auth_service
    success, msg = email_auth_service.email_service.send_email(
        to_email=to,
        subject=subject,
        html_content=f"<p>{body}</p>",
        text_content=body,
    )
    return {"sent": success, "to": to, "subject": subject, "message": msg}


async def _escalate_to_human(phone_number: str, reason: str, client_id: int = 1):
    from handoff import request_handoff, send_telegram_message
    await request_handoff(phone_number, reason, confidence=0.0)
    await send_telegram_message(
        f"Escalation Request\nPhone: {phone_number}\nReason: {reason}\nClient: {client_id}",
        phone_number,
    )
    from db import async_session, ConversationSession
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(
            select(ConversationSession).where(
                ConversationSession.client_id == client_id,
                ConversationSession.phone_number == phone_number,
            )
        )
        conv = result.scalar_one_or_none()
        if conv:
            conv.is_human_takeover = True
            conv.session_state = "human_takeover"
            conv.context = conv.context or {}
            conv.context["human_takeover_reason"] = reason
            await session.commit()
    return {
        "status": "escalated",
        "phone_number": phone_number,
        "reason": reason,
        "message": "Conversation has been handed off to a human agent.",
    }


async def _update_lead_score(phone_number: str, score_delta: float, client_id: int = 1):
    from services.lead_scoring import scoring_engine, LeadSignal
    engine = scoring_engine
    profile = engine.get_profile(phone_number, client_id)
    profile.score = max(0, min(100, profile.score + score_delta))
    if profile.score >= 60:
        profile.tier = engine.tier.HOT
    elif profile.score >= 30:
        profile.tier = engine.tier.WARM
    else:
        profile.tier = engine.tier.COLD
    engine._recalculate(profile)
    return {
        "phone_number": phone_number,
        "new_score": round(profile.score, 1),
        "tier": profile.tier.value,
        "delta": score_delta,
    }


# ---------------------------------------------------------------------------
# Global registry and auto-registration
# ---------------------------------------------------------------------------

tool_registry = ToolRegistry()

tool_registry.register(Tool(
    name="check_calendar",
    description="Check available appointment slots for a given date",
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "duration_minutes": {"type": "integer", "description": "Duration of the appointment in minutes", "default": 30},
            "client_id": {"type": "integer", "description": "Client/business ID", "default": 1},
        },
        "required": ["date"],
    },
    callable=_check_calendar,
    requires_confirmation=False,
))

tool_registry.register(Tool(
    name="create_appointment",
    description="Book an appointment for a customer. Requires explicit confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "phone_number": {"type": "string", "description": "Customer phone number"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM format"},
            "title": {"type": "string", "description": "Title/purpose of the appointment"},
            "client_id": {"type": "integer", "description": "Client/business ID", "default": 1},
        },
        "required": ["phone_number", "date", "time", "title"],
    },
    callable=_create_appointment,
    requires_confirmation=True,
))

tool_registry.register(Tool(
    name="lookup_product",
    description="Search the business catalog for products or services",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query for products/services"},
            "client_id": {"type": "integer", "description": "Client/business ID", "default": 1},
        },
        "required": ["query"],
    },
    callable=_lookup_product,
    requires_confirmation=False,
))

tool_registry.register(Tool(
    name="send_email",
    description="Send an email to a customer. Requires explicit confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body content"},
            "client_id": {"type": "integer", "description": "Client/business ID", "default": 1},
        },
        "required": ["to", "subject", "body"],
    },
    callable=_send_email,
    requires_confirmation=True,
))

tool_registry.register(Tool(
    name="escalate_to_human",
    description="Hand off the conversation to a human agent.",
    parameters={
        "type": "object",
        "properties": {
            "phone_number": {"type": "string", "description": "Customer phone number"},
            "reason": {"type": "string", "description": "Reason for escalation"},
            "client_id": {"type": "integer", "description": "Client/business ID", "default": 1},
        },
        "required": ["phone_number", "reason"],
    },
    callable=_escalate_to_human,
    requires_confirmation=False,
))

tool_registry.register(Tool(
    name="update_lead_score",
    description="Update a lead's score by a delta value",
    parameters={
        "type": "object",
        "properties": {
            "phone_number": {"type": "string", "description": "Customer phone number"},
            "score_delta": {"type": "number", "description": "Points to add (positive) or subtract (negative)"},
            "client_id": {"type": "integer", "description": "Client/business ID", "default": 1},
        },
        "required": ["phone_number", "score_delta"],
    },
    callable=_update_lead_score,
    requires_confirmation=False,
))
