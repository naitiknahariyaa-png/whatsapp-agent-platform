import os
import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import redis
from sqlalchemy import select, update
from db import async_session, Contact, ConversationSession

logger = logging.getLogger("memory_manager")

class MemoryManager:
    \"\"\"
    Three-Layer Memory System:
    1. Session Memory (Redis) - Short-term context.
    2. Entity Memory (Postgres) - Persistent user facts.
    3. Semantic Memory (ChromaDB) - Business knowledge.
    \"\"\"
    def __init__(self):
        # Redis setup for Session Memory
        self.redis_url = os.getenv(\"REDIS_URL\", \"redis://localhost:6379/0\")
        try:
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self.redis.ping()
            self.redis_available = True
        except Exception as e:
            logger.error(f\"Redis unavailable: {e}\")
            self.redis_available = False
        
        self.session_ttl = 3600 * 2 # 2 hours

    # --- Layer 1: Session Memory (Redis) ---
    async def get_session_memory(self, phone_number: str) -> Dict[str, Any]:
        if not self.redis_available: return {}
        try:
            data = self.redis.get(f\"session:{phone_number}\")
            return json.loads(data) if data else {}
        except Exception:
            return {}

    async def set_session_memory(self, phone_number: str, data: Dict[str, Any]):
        if not self.redis_available: return
        try:
            self.redis.setex(f\"session:{phone_number}\", self.session_ttl, json.dumps(data))
        except Exception:
            pass

    # --- Layer 2: Entity Memory (Postgres) ---
    async def get_entity_memory(self, phone_number: str, client_id: int) -> Dict[str, Any]:
        \"\"\"Retrieve permanent facts about a lead (e.g. budget, preference)\"\"\"
        async with async_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.phone_number == phone_number, Contact.client_id == client_id)
            )
            contact = result.scalar_one_or_none()
            if not contact:
                return {}
            # Return custom_fields which acts as our Entity store
            return contact.custom_fields or {}

    async def upsert_entity(self, phone_number: str, client_id: int, entities: Dict[str, Any]):
        \"\"\"Save new facts found in conversation to the lead profile\"\"\"
        async with async_session() as session:
            result = await session.execute(
                select(Contact).where(Contact.phone_number == phone_number, Contact.client_id == client_id)
            )
            contact = result.scalar_one_or_none()
            if not contact:
                # Create contact if doesn't exist
                from db import Contact
                contact = Contact(phone_number=phone_number, client_id=client_id, custom_fields={})
                session.add(contact)
            
            # Merge new entities into existing ones
            current_fields = contact.custom_fields or {}
            current_fields.update(entities)
            contact.custom_fields = current_fields
            await session.commit()

    # --- Layer 3: Semantic Memory (ChromaDB) ---
    async def get_semantic_context(self, query: str, client_id: int) -> str:
        \"\"\"Search business-wide knowledge base for relevant facts\"\"\"
        from vector_store import VectorStore
        vs = VectorStore()
        try:
            # Search specifically for this client's business data
            results = await vs.search(query, client_id=client_id, limit=3)
            if not results: return \"No specific business knowledge found.\"
            
            context = \"\\n\".join([r['content'] for r in results])
            return f\"Company Knowledge Base:\\n{context}\"
        except Exception as e:
            logger.error(f\"Semantic memory error: {e}\")
            return \"Knowledge base currently unavailable.\"

    # --- Extraction Loop ---
    async def extract_entities(self, user_input: str, phone_number: str, client_id: int) -> Dict[str, Any]:
        \"\"\"
        Runs a lightweight pass to see if the user stated a fact worth remembering.
        If so, it updates the Entity Memory.
        \"\"\"
        from llm_setup import get_llm
        llm = get_llm()
        
        extraction_prompt = (
            f\"User said: '{user_input}'\\n\\n\"
            \"Extract any permanent facts (budget, preferred time, location, goal) into JSON. \"
            \"If no facts are present, return {}. Example: {\\\"budget\\\": \\\"50000\\\", \\\"city\\\": \\\"Delhi\\\"}\"
        )
        
        try:
            res = await llm.ainvoke([{\"role\": \"user\", \"content\": extraction_prompt}])
            content = res.content if hasattr(res, 'content') else str(res)
            
            import re
            match = re.search(r'\\{.*\\}', content, re.DOTALL)
            if match:
                entities = json.loads(match.group(0))
                if entities:
                    await self.upsert_entity(phone_number, client_id, entities)
                    return entities
        except Exception as e:
            logger.error(f\"Entity extraction failed: {e}\")
        
        return {}

# Global instance
memory_manager = MemoryManager()
