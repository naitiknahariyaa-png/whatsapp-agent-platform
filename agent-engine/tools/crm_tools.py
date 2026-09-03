from tools.dispatcher import tool_dispatcher
from db import async_session, Lead
from sqlalchemy import select


def _norm(phone_number: str) -> str:
    """Strip formatting so '+91 98765-43210' matches '919876543210'."""
    return "".join(c for c in (phone_number or "") if c.isdigit())


async def get_lead_info(phone_number: str):
    """Fetch full lead details from CRM."""
    digits = _norm(phone_number)
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.phone_number == digits))
        lead = result.scalar_one_or_none()
        if lead:
            return {
                "name": lead.name,
                "status": lead.status,
                "score": lead.lead_score,
                "source": lead.source,
                "requirement": lead.requirement,
            }
        return {"status": "not_found", "message": "No lead record yet - treat as a brand-new customer."}


async def update_lead_status(phone_number: str, status: str):
    """Update lead status (e.g. from 'new' to 'qualified')"""
    digits = _norm(phone_number)
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.phone_number == digits))
        lead = result.scalar_one_or_none()
        if lead:
            lead.status = status
            await session.commit()
            return f"Lead {digits} updated to {status}."
        # Auto-create the lead so the CRM never dead-ends the agent.
        session.add(Lead(client_id=1, phone_number=digits, status=status, source="whatsapp"))
        await session.commit()
        return f"New lead {digits} created with status {status}."

# Register tools to the dispatcher
tool_dispatcher.register("get_lead_info", get_lead_info)
tool_dispatcher.register("update_lead_status", update_lead_status)
