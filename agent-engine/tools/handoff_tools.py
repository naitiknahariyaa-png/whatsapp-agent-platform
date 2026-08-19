import logging
from typing import Dict, Any
from tools.dispatcher import tool_dispatcher
from db import async_session, ConversationSession
from sqlalchemy import select, update

logger = logging.getLogger(\"handoff_tools\")

async def escalate_to_human(phone_number: str, reason: str, urgency: str = \"medium\"):
    \"\"\"
    Triggers a human handoff. 
    Marks the session as human-controlled and logs the reason/urgency.
    \"\"\"
    try:
        async with async_session() as session:
            # 1. Find the active session for this user
            result = await session.execute(
                select(ConversationSession).where(
                    ConversationSession.phone_number == phone_number
                ).order_by(ConversationSession.last_activity_at.desc()).limit(1)
            )
            conv_session = result.scalar_one_or_none()
            
            if not conv_session:
                return {\"status\": \"error\", \"message\": \"No active session found to escalate.\"}
            
            # 2. Mark for human takeover
            conv_session.is_human_takeover = True
            conv_session.context = conv_session.context or {}
            conv_session.context[\"handoff\"] = {
                \"reason\": reason,
                \"urgency\": urgency,
                \"timestamp\": __import__('datetime').datetime.now().isoformat()
            }
            
            await session.commit()
            
            # In production, this is where you'd trigger a Telegram/Email notification to the human agent
            logger.warning(f\"[HANDOFF] User {phone_number} escalated! Reason: {reason} | Urgency: {urgency}\")
            
            return {
                \"status\": \"success\", 
                \"message\": \"Conversation successfully escalated to a human agent.\"
            }
    except Exception as e:
        logger.error(f\"Handoff error: {e}\")
        return {\"status\": \"error\", \"message\": str(e)}

# Register tool
tool_dispatcher.register(\"escalate_to_human\", escalate_to_human)
