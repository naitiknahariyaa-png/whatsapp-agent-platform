"""
Memory & Personalization Functions
Make the bot feel like it remembers — without bloating context.
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Redis client (initialized lazily)
_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            "redis://localhost:6379/0",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_client


# =============================================================================
# 3.1 extract_entities — Small LLM call, huge personalization impact
# =============================================================================
async def extract_entities(
    message_text: str,
    existing_entities: Optional[Dict] = None,
    llm=None,
) -> Dict[str, Any]:
    """
    Small LLM call: pulls budget, name, preferred time, etc. from a message.
    This single function is what makes the bot feel like it 'remembers' someone.
    
    Args:
        message_text: User's message
        existing_entities: Previously known entities (to avoid re-extraction)
        llm: Optional LLM instance
    
    Returns:
        Dictionary of extracted entities (only new/updated ones)
    """
    if llm is None:
        # Import lazily to avoid circular imports
        from llm_setup import get_llm
        llm = get_llm()
    
    # Known entities to not re-extract
    known = existing_entities or {}
    known_keys = set(known.keys())
    
    # Fields we care about extracting
    extraction_fields = [
        "name", "budget", "budget_min", "budget_max",
        "preferred_date", "preferred_time", "timezone",
        "location", "city", "state", "pincode",
        "email", "phone", "alternate_phone",
        "requirement", "urgency", "preferred_language",
        "company_name", "designation", "industry",
    ]
    
    # Skip already-known fields
    to_extract = [f for f in extraction_fields if f not in known_keys]
    if not to_extract:
        return {}
    
    prompt = f"""Extract specific facts from the user's message.
Only return JSON with fields that are explicitly mentioned.
Fields to watch for: {', '.join(to_extract)}

User message: "{message_text}"

Return ONLY valid JSON. If no facts found, return {{}}.
Example: {{"budget": "50000", "preferred_time": "evening", "city": "Mumbai"}}"""
    
    try:
        # Use the LLM with structured output
        if hasattr(llm, 'ainvoke'):
            response = await llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
        else:
            response = await llm.generate([{"role": "user", "content": prompt}])
            content = response.get("content", "")
        
        # Parse JSON from response
        import re
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            extracted = json.loads(match.group(0))
            # Filter out empty/null values
            return {k: v for k, v in extracted.items() if v not in (None, "", [])}
    except Exception as e:
        logging.getLogger(__name__).warning(f"Entity extraction failed: {e}")
    
    return {}


# =============================================================================
# 3.2 merge_entity_update — Smart merge without data corruption
# =============================================================================
def merge_entity_update(
    existing: Dict[str, Any],
    new_entities: Dict[str, Any],
    protect_fields: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Merges new extracted facts without overwriting good data with null/uncertain ones.
    Prevents memory corruption (e.g. a joke reply overwriting a real budget figure).
    
    Args:
        existing: Current entity store
        new_entities: Newly extracted entities
        protect_fields: Fields that should never be overwritten once set (e.g., 'name', 'email')
    
    Returns:
        Merged entity dictionary
    """
    if protect_fields is None:
        protect_fields = {"name", "email", "phone", "created_at"}
    
    merged = existing.copy()
    
    for key, new_value in new_entities.items():
        # Skip if new value is empty/null
        if new_value in (None, "", [], {}):
            continue
        
        existing_value = merged.get(key)
        
        # Never overwrite protected fields once set
        if key in protect_fields and existing_value not in (None, "", [], {}):
            continue
        
        # For numeric fields, keep the more specific/realistic value
        if isinstance(new_value, (int, float)) and isinstance(existing_value, (int, float)):
            # If existing is a reasonable value, keep it unless new is more specific
            if existing_value > 0 and (new_value <= 0 or abs(new_value - existing_value) / existing_value > 0.5):
                continue  # Don't overwrite reasonable existing with suspicious new
        
        # For strings, prefer non-empty, more specific
        if isinstance(new_value, str) and isinstance(existing_value, str):
            if len(new_value.strip()) < 2:
                continue  # Don't overwrite with near-empty string
            if existing_value and len(new_value) <= len(existing_value):
                # Only update if new is more informative
                pass
        
        merged[key] = new_value
    
    return merged


# =============================================================================
# 3.3 summarize_conversation — Rolling summary for long context
# =============================================================================
async def summarize_conversation(
    history: List[Dict[str, Any]],
    max_tokens: int = 500,
    llm=None,
) -> str:
    """
    Rolling summary of older turns.
    Keeps context window small and cheap on long-running leads.
    
    Args:
        history: List of message dicts with 'role', 'content', 'timestamp'
        max_tokens: Approximate token budget for summary
        llm: Optional LLM instance
    
    Returns:
        Concise summary string
    """
    if not history:
        return ""
    
    if llm is None:
        from llm_setup import get_llm
        llm = get_llm()
    
    # Format recent history (last 20 messages)
    recent = history[-20:] if len(history) > 20 else history
    
    formatted = "\n".join([
        f"{msg.get('role', 'user')}: {msg.get('content', '')[:200]}"
        for msg in recent
    ])
    
    prompt = f"""Summarize this conversation in 3-4 sentences focusing on:
- User's main goal/intent
- Key facts gathered (budget, timeline, requirements)
- Current status (what's pending, what's decided)
- Any blockers or objections

Conversation:
{formatted}

Summary:"""
    
    try:
        if hasattr(llm, 'ainvoke'):
            response = await llm.ainvoke(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        else:
            response = await llm.generate([{"role": "user", "content": prompt}])
            return response.get("content", "")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Summarization failed: {e}")
        return "Conversation summary unavailable."


def summarize_conversation_sync(
    history: List[Dict[str, Any]],
    max_tokens: int = 500,
) -> str:
    """Synchronous version using simple heuristic (no LLM)."""
    if not history:
        return ""
    
    # Simple heuristic summary
    topics = set()
    intents = []
    last_intent = None
    
    for msg in history[-10:]:
        content = msg.get('content', '').lower()
        if any(kw in content for kw in ['budget', 'price', 'cost', 'fee']):
            topics.add('budget')
        if any(kw in content for kw in ['appointment', 'book', 'schedule', 'meeting']):
            topics.add('appointment')
        if any(kw in content for kw in ['document', 'upload', 'send', 'share']):
            topics.add('documents')
        if any(kw in content for kw in ['question', 'help', 'how', 'what', 'why']):
            topics.add('questions')
    
    summary_parts = []
    if topics:
        summary_parts.append(f"Topics discussed: {', '.join(sorted(topics))}")
    
    # Get last user message
    for msg in reversed(history):
        if msg.get('role') == 'user':
            summary_parts.append(f"Last user message: {msg.get('content', '')[:100]}")
            break
    
    return " | ".join(summary_parts) if summary_parts else "No summary available."


# =============================================================================
# 3.4 is_pii — Flag sensitive fields before they leak
# =============================================================================
PII_FIELD_PATTERNS = {
    "phone": [r"phone", r"mobile", r"contact", r"whatsapp"],
    "email": [r"email", r"e-mail", r"mail"],
    "aadhaar": [r"aadhaar", r"aadhar"],
    "pan": [r"pan", r"permanent.*account"],
    "credit_card": [r"credit.*card", r"card.*number"],
    "bank_account": [r"bank.*account", r"account.*number", r"ifsc"],
    "address": [r"address", r"location"],
    "name": [r"name", r"full.*name"],
    "dob": [r"dob", r"date.*of.*birth", r"birth.*date"],
    "password": [r"password", r"passwd", r"secret"],
    "api_key": [r"api.*key", r"access.*token", r"secret.*key"],
}

PII_VALUE_PATTERNS = {
    "phone": r"\+?\d{10,15}",
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "aadhaar": r"\d{4}\s?\d{4}\s?\d{4}",
    "pan": r"[A-Z]{5}\d{4}[A-Z]",
    "credit_card": r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}",
}


def is_pii(field_name: str, value: Optional[str] = None) -> bool:
    """
    Flags sensitive fields before logging/caching.
    One check that prevents PII from leaking into logs, caches, or LLM prompts unnecessarily.
    
    Args:
        field_name: Name of the field (e.g., 'phone_number', 'email')
        value: Optional value to also check against value patterns
    
    Returns:
        True if field is likely PII
    """
    field_lower = field_name.lower()
    
    # Check field name patterns
    for pii_type, patterns in PII_FIELD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, field_lower):
                return True
    
    # Also check value patterns if provided
    if value and isinstance(value, str):
        for pii_type, pattern in PII_VALUE_PATTERNS.items():
            if re.search(pattern, value):
                return True
    
    return False


def scrub_pii(data: Dict[str, Any], mask: str = "[REDACTED]") -> Dict[str, Any]:
    """Recursively scrub PII from a dictionary."""
    scrubbed = {}
    for key, value in data.items():
        if is_pii(key, value if isinstance(value, str) else None):
            scrubbed[key] = mask
        elif isinstance(value, dict):
            scrubbed[key] = scrub_pii(value, mask)
        elif isinstance(value, list):
            scrubbed[key] = [
                scrub_pii(v, mask) if isinstance(v, dict) else mask if is_pii("", v) else v
                for v in value
            ]
        else:
            scrubbed[key] = value
    return scrubbed


# =============================================================================
# 3.5 ttl_for_memory_type — Prevents Redis bloat
# =============================================================================
MEMORY_TTL_MAP = {
    "session": 7200,           # 2 hours - short-term conversation context
    "entity": 2592000,         # 30 days - persistent user facts
    "semantic": 604800,        # 7 days - retrieved knowledge chunks
    "lead_scoring": 86400,     # 1 day - lead scores decay daily
    "conversation_summary": 86400,  # 1 day - rolling summaries
    "appointment_reminder": 86400, # 1 day - reminder state
    "rate_limit": 60,          # 1 minute - rate limiting
    "heartbeat": 120,          # 2 minutes - service health
    "idempotency": 3600,       # 1 hour - deduplication
    "media_dedupe": 604800,    # 7 days - media hash memory
    "opt_out": 31536000,       # 1 year - opt-out persistence
}

def ttl_for_memory_type(memory_type: str) -> int:
    """
    Returns expiry duration per memory type.
    Stops Redis from silently filling up with stale sessions.
    
    Args:
        memory_type: Type of memory (e.g., 'session', 'entity', 'semantic')
    
    Returns:
        TTL in seconds
    """
    return MEMORY_TTL_MAP.get(memory_type, 3600)  # Default 1 hour


def get_redis_key(memory_type: str, identifier: str) -> str:
    """Generate standardized Redis key with TTL hint."""
    return f"{memory_type}:{identifier}"


async def set_with_ttl(
    memory_type: str,
    identifier: str,
    value: Any,
    redis_client: Optional[redis.Redis] = None,
):
    """Set a value with automatic TTL based on memory type."""
    if redis_client is None:
        redis_client = _get_redis()
    
    key = get_redis_key(memory_type, identifier)
    ttl = ttl_for_memory_type(memory_type)
    import json
    await redis_client.setex(key, ttl, json.dumps(value, default=str))