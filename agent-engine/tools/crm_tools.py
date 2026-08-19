from tools.dispatcher import tool_dispatcher
from db import async_session, Lead
from sqlalchemy import select

async def get_lead_info(phone_number: str):
    \"\"\"Fetch full lead details from CRM\"\"\"
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.phone == phone_number))
        lead = result.scalar_one_or_none()
        if lead:
            return {
                \"name\": lead.name,
                \"status\": lead.status,
                \"score\": lead.score,
                \"source\": lead.source
            }
        return \"Lead not found in CRM.\"

async def update_lead_status(phone_number: str, status: str):
    \"\"\"Update lead status (e.g. from 'new' to 'qualified')\"\"\"
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.phone == phone_number))
        lead = result.scalar_one_or_none()
        if lead:
            lead.status = status
            await session.commit()
            return f\"Lead {phone_number} updated to {status}.\"
        return \"Lead not found.\"

# Register tools to the dispatcher
tool_dispatcher.register(\"get_lead_info\", get_lead_info)
tool_dispatcher.register(\"update_lead_status\", update_lead_status)
