import logging
from agents.manager import ManagerAgent
from memory_manager import memory_manager
from db import async_session, ConversationSession
from sqlalchemy import select

logger = logging.getLogger(\"orchestrator\")

# The Company CEO
manager = ManagerAgent()

async def process_incoming_message(phone_number: str, message: str, client_id: int = 1):
    try:
        # 1. Check for Human Takeover FIRST
        # If a human is already handling the chat, AI should stay silent.
        async with async_session() as session:
            result = await session.execute(
                select(ConversationSession).where(
                    ConversationSession.phone_number == phone_number,
                    ConversationSession.client_id == client_id
                ).order_by(ConversationSession.last_activity_at.desc()).limit(1)
            )
            conv_session = result.scalar_one_or_none()
            
            if conv_session and conv_session.is_human_takeover:
                logger.info(f\"[BLOCK] Session for {phone_number} is under human control. AI idling.\")
                return None # Return None to signal the bridge NOT to send an AI reply

            # 2. Entity Extraction (Automated background loop)
            # Note: Moved inside the session block for consistency
            # (Actual call to memory_manager is async)
            
        # We must call this outside the session context or use a fresh one
        # because memory_manager.extract_entities creates its own session.
        await memory_manager.extract_entities(message, phone_number, client_id)

        # 3. Context Preparation
        async with async_session() as session:
            # Re-fetch session to get latest state
            result = await session.execute(
                select(ConversationSession).where(
                    ConversationSession.phone_number == phone_number,
                    ConversationSession.client_id == client_id
                )
            )
            conv_session = result.scalar_one_or_none()
            
            context = {
                \"phone_number\": phone_number,
                \"client_id\": client_id,
                \"session_state\": conv_session.session_state if conv_session else \"browsing\",
                \"entities\": conv_session.entities if conv_session else {}
            }

            # 4. Manager Orchestration
            logger.info(f\"Routing message from {phone_number} to the CEO...\")
            final_response = await manager.run(message, context=context)

            # 5. Session Update
            if conv_session:
                conv_session.last_user_message = message
                conv_session.last_bot_message = final_response
                await session.commit()
            
            return final_response

    except Exception as e:
        logger.error(f\"Orchestration failure: {e}\", exc_info=True)
        return \"I'm having some trouble organizing my team. Please try again in a moment!\"
