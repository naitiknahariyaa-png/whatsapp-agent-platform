"""
Messaging & Anti-Ban Functions
Small guards with huge downside if missing.
"""
import asyncio
import hashlib
import random
import re
from typing import List, Optional, Set
import redis.asyncio as redis
from datetime import datetime, timezone

# Global Redis client (initialized lazily)
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
# 1.1 is_duplicate_message — Prevents double-processing on webhook retries
# =============================================================================
async def is_duplicate_message(msg_id: str, ttl_seconds: int = 86400) -> bool:
    """
    Checks a Redis set of recently-seen message IDs before processing.
    WhatsApp/webhooks retry on timeout — without this you double-reply or double-charge.
    
    Args:
        msg_id: Unique message identifier (wamid or similar)
        ttl_seconds: How long to keep the ID (default 24h)
    
    Returns:
        True if this is a duplicate (already processed), False if new
    """
    r = _get_redis()
    key = f"processed_msg:{msg_id}"
    # SET NX = only set if not exists (atomic)
    was_new = await r.set(key, "1", nx=True, ex=ttl_seconds)
    return was_new is False  # False = already existed = duplicate


# =============================================================================
# 1.2 typing_indicator — Human-like bot behavior
# =============================================================================
async def typing_indicator(
    bridge_url: str,
    chat_id: str,
    duration: float = 2.0,
    auth_token: Optional[str] = None,
) -> bool:
    """
    Sends a 'typing…' signal before the real reply.
    Makes the bot feel human, reduces users spamming multiple messages while waiting.
    
    Args:
        bridge_url: Base URL of the WhatsApp bridge (e.g., http://localhost:3001)
        chat_id: WhatsApp chat ID (e.g., '919876543210@c.us')
        duration: How long to show typing indicator (seconds)
        auth_token: Optional auth token for bridge
    
    Returns:
        True if successfully sent
    """
    import httpx
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{bridge_url}/chat/typing",
                json={"chat_id": chat_id, "duration": duration},
                headers=headers,
            )
        # Actually wait the duration so it feels real
        await asyncio.sleep(min(duration, 3.0))
        return True
    except Exception:
        return False


# =============================================================================
# 1.3 split_long_message — WhatsApp-safe chunking
# =============================================================================
def split_long_message(
    text: str,
    max_len: int = 4096,
    prefer_sentence_boundary: bool = True,
) -> List[str]:
    """
    Breaks a long AI response into WhatsApp-safe chunks at sentence boundaries.
    Prevents silent truncation or failed sends on long RAG answers.
    
    Args:
        text: The full message text
        max_len: Maximum length per chunk (WhatsApp limit is 4096)
        prefer_sentence_boundary: Try to split at sentence endings
    
    Returns:
        List of message chunks
    """
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    remaining = text
    
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        
        # Try to find a good split point
        split_at = max_len
        if prefer_sentence_boundary:
            # Look for sentence endings within the last 20% of the chunk
            search_start = max(0, max_len - int(max_len * 0.2))
            # Find last sentence ending (., !, ?) followed by space or end
            for i in range(max_len - 1, search_start - 1, -1):
                if remaining[i] in '.!?' and (i + 1 == len(remaining) or remaining[i + 1] in ' \n'):
                    split_at = i + 1
                    break
        
        chunk = remaining[:split_at].strip()
        chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    
    return chunks


# =============================================================================
# 1.4 randomized_delay — Biggest anti-ban lever
# =============================================================================
async def randomized_delay(min_seconds: float = 5.0, max_seconds: float = 15.0) -> float:
    """
    Sleeps a random interval before sending.
    Single biggest lever against ban-detection heuristics.
    
    Args:
        min_seconds: Minimum delay
        max_seconds: Maximum delay
    
    Returns:
        Actual delay that was applied
    """
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)
    return delay


# =============================================================================
# 1.5 is_opted_out — Legal/compliance guard
# =============================================================================
async def is_opted_out(phone_number: str) -> bool:
    """
    Checks a stop-list before any automated send.
    Legal/compliance requirement, and a one-line function that prevents a support nightmare.
    
    Args:
        phone_number: E.164 formatted phone number
    
    Returns:
        True if opted out, False otherwise
    """
    r = _get_redis()
    return await r.sismember("opted_out_numbers", phone_number)


# =============================================================================
# 1.6 detect_stop_keyword — Multi-language opt-out detection
# =============================================================================
STOP_KEYWORDS = {
    "en": ["stop", "unsubscribe", "unsub", "opt out", "optout", "no more", "quit", "cancel"],
    "hi": ["रोकें", "बंद", "नहीं चाहिए", "अनसब्सक्राइब", "रोक दो"],
    "es": ["parar", "cancelar", "no más", "basta", "desuscribir"],
    "fr": ["arrêter", "annuler", "plus", "se désabonner"],
    "ar": ["إيقاف", "إلغاء", "لا أريد", "انسحب"],
}

def detect_stop_keyword(text: str, languages: Optional[List[str]] = None) -> bool:
    """
    Flags 'stop', 'unsubscribe', 'बंद', etc. in multiple languages.
    Feeds directly into the opt-out check above.
    
    Args:
        text: User message text
        languages: Optional list of language codes to check (default: all)
    
    Returns:
        True if stop keyword detected
    """
    if languages is None:
        languages = list(STOP_KEYWORDS.keys())
    
    normalized = text.lower().strip()
    
    for lang in languages:
        for keyword in STOP_KEYWORDS.get(lang, []):
            if keyword in normalized:
                return True
    return False


# =============================================================================
# 1.7 normalize_phone_number — E.164 standardization
# =============================================================================
def normalize_phone_number(raw: str) -> Optional[str]:
    """
    Strips formatting, applies E.164 standard.
    Prevents duplicate leads for the same person saved two different ways.
    
    Args:
        raw: Phone number in any format (+91 98765 43210, 9876543210, etc.)
    
    Returns:
        E.164 formatted number (e.g., +919876543210) or None if invalid
    """
    if not raw:
        return None
    
    # Keep only digits and +
    cleaned = re.sub(r'[^\d+]', '', raw.strip())
    
    # Handle leading 00 vs +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    elif not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    
    # Validate: should be + followed by 10-15 digits
    digits_only = cleaned[1:] if cleaned.startswith("+") else cleaned
    if not digits_only.isdigit() or len(digits_only) < 10 or len(digits_only) > 15:
        return None
    
    return "+" + digits_only


# =============================================================================
# 1.8 dedupe_incoming_media — Skip reprocessing identical media
# =============================================================================
async def dedupe_incoming_media(media_hash: str, ttl_seconds: int = 604800) -> bool:
    """
    Skips reprocessing an identical forwarded image/doc.
    Saves LLM vision-call cost on forwarded spam/memes.
    
    Args:
        media_hash: SHA256 hash of the media content
        ttl_seconds: How long to remember (default 7 days)
    
    Returns:
        True if this is a duplicate, False if new
    """
    r = _get_redis()
    key = f"media_hash:{media_hash}"
    was_new = await r.set(key, "1", nx=True, ex=ttl_seconds)
    return was_new is False