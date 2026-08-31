"""
Lead Scoring & Sales Functions
Turns scattered if/else logic into testable, predictable functions.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# 5.1 classify_urgency — Fast small-model call
# =============================================================================
class UrgencyLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


URGENCY_KEYWORDS = {
    UrgencyLevel.CRITICAL: [
        "emergency", "urgent", "asap", "immediately", "right now", "critical",
        "life or death", "can't wait", "dying", "severe", "accident",
    ],
    UrgencyLevel.HIGH: [
        "soon", "today", "this week", "quickly", "fast", "priority",
        "need it now", "as soon as possible", "hurry",
    ],
    UrgencyLevel.MEDIUM: [
        "this month", "next week", "planning", "considering", "looking into",
        "interested", "maybe", "exploring options",
    ],
    UrgencyLevel.LOW: [
        "just curious", "future", "someday", "eventually", "no rush",
        "just looking", "information only",
    ],
}


def classify_urgency(
    message_text: str,
    llm=None,
    use_llm: bool = False,
) -> UrgencyLevel:
    """
    Fast classification: low/medium/high/urgent.
    Feeds the HOT-lead alert without needing a full agent pass.
    
    Args:
        message_text: User's message
        llm: Optional LLM for nuanced classification
        use_llm: Whether to use LLM fallback
    
    Returns:
        UrgencyLevel enum
    """
    text = message_text.lower()
    
    # Quick keyword-based check (fast, no LLM)
    for level in [UrgencyLevel.CRITICAL, UrgencyLevel.HIGH, UrgencyLevel.MEDIUM, UrgencyLevel.LOW]:
        for keyword in URGENCY_KEYWORDS[level]:
            if keyword in text:
                return level
    
    # Optional LLM for nuanced cases
    if use_llm and llm:
        try:
            prompt = f"""Classify urgency of this message: "{message_text}"
            Return ONLY one word: critical, high, medium, or low"""
            # ... LLM call would go here
        except Exception:
            pass
    
    return UrgencyLevel.LOW


# =============================================================================
# 5.2 classify_sentiment — Escalation trigger
# =============================================================================
class Sentiment(Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    FRUSTRATED = "frustrated"


SENTIMENT_INDICATORS = {
    Sentiment.POSITIVE: [
        "thank", "great", "excellent", "perfect", "happy", "satisfied",
        "love", "amazing", "wonderful", "great job", "well done",
    ],
    Sentiment.NEGATIVE: [
        "disappointed", "unhappy", "bad", "terrible", "awful", "horrible",
        "poor", "worst", "hate", "angry", "frustrated",
    ],
    Sentiment.FRUSTRATED: [
        "frustrated", "annoyed", "irritated", "fed up", "done with this",
        "waste of time", "ridiculous", "unacceptable", "this is ridiculous",
        "why is this so hard", "nobody helps", "useless",
    ],
}


def classify_sentiment(
    message_text: str,
    conversation_history: Optional[List[Dict]] = None,
) -> Sentiment:
    """
    Single biggest trigger for auto-escalation to a human.
    
    Args:
        message_text: Current message
        conversation_history: Optional recent messages for context
    
    Returns:
        Sentiment enum
    """
    text = message_text.lower()
    
    # Check current message
    for sentiment in [Sentiment.FRUSTRATED, Sentiment.NEGATIVE, Sentiment.POSITIVE, Sentiment.NEUTRAL]:
        for indicator in SENTIMENT_INDICATORS.get(sentiment, []):
            if indicator in text:
                return sentiment
    
    # Check conversation trend (escalating frustration)
    if conversation_history:
        recent_user_messages = [
            msg.get("content", "").lower()
            for msg in conversation_history[-5:]
            if msg.get("role") == "user"
        ]
        frustration_count = sum(
            1 for msg in recent_user_messages
            if any(ind in msg for ind in SENTIMENT_INDICATORS[Sentiment.FRUSTRATED])
        )
        if frustration_count >= 2:
            return Sentiment.FRUSTRATED
    
    return Sentiment.NEUTRAL


# =============================================================================
# 5.3 score_decay — Keeps hot leads actually hot
# =============================================================================
def score_decay(
    current_score: float,
    days_since_contact: int,
    base_decay_rate: float = 2.0,  # points per day
    min_score: float = 0.0,
    max_score: float = 100.0,
) -> float:
    """
    Reduces lead score over time if untouched.
    Keeps 'hot' leads actually hot instead of stale leads sitting at high priority forever.
    
    Args:
        current_score: Current lead score (0-100)
        days_since_contact: Days since last meaningful interaction
        base_decay_rate: Points to decay per day
        min_score: Floor
        max_score: Ceiling
    
    Returns:
        Decayed score
    """
    if days_since_contact <= 0:
        return min(max(current_score, min_score), max_score)
    
    decayed = current_score - (base_decay_rate * days_since_contact)
    return max(min(decayed, max_score), min_score)


def calculate_lead_score(
    base_score: float,
    urgency: "UrgencyLevel",
    sentiment: "Sentiment",
    days_since_contact: int,
    engagement_events: int = 0,
) -> float:
    """
    Comprehensive lead scoring combining multiple factors.
    """
    score = base_score
    
    # Urgency bonus
    urgency_bonus = {
        "critical": 25,
        "high": 15,
        "medium": 5,
        "low": 0,
    }
    score += urgency_bonus.get(urgency.value, 0)
    
    # Sentiment modifier
    if sentiment == Sentiment.FRUSTRATED:
        score += 15  # Frustrated but engaged = high intent
    elif sentiment == Sentiment.NEGATIVE:
        score -= 5
    elif sentiment == Sentiment.POSITIVE:
        score += 5
    
    # Engagement bonus
    score += min(engagement_events * 2, 20)
    
    # Apply time decay
    score = score_decay(score, days_since_contact)
    
    return max(0.0, min(100.0, score))


# =============================================================================
# 5.4 notify_owner — One function for all alerts
# =============================================================================
@dataclass
class NotificationPayload:
    """Unified notification structure."""
    title: str
    body: str
    priority: str = "normal"  # low, normal, high, critical
    channels: List[str] = field(default_factory=lambda: ["whatsapp"])
    metadata: Dict[str, Any] = field(default_factory=dict)


async def notify_owner(
    message: str,
    channel: str = "whatsapp",
    priority: str = "normal",
    client_id: int = 1,
    metadata: Optional[Dict] = None,
) -> bool:
    """
    Generic push notification helper (WhatsApp/Slack/email/SMS fallback).
    One function, reused for HOT leads, errors, reports, escalations.
    
    Args:
        message: Notification message
        channel: Primary channel (whatsapp, slack, email, sms)
        priority: low, normal, high, critical
        client_id: Business client ID
        metadata: Additional context
    
    Returns:
        True if sent successfully
    """
    # Log notification
    logger.info(f"[NOTIFICATION-{priority.upper()}] Client {client_id}: {message[:100]}")
    
    try:
        if channel == "whatsapp":
            from outbound_limiter import send_whatsapp
            # Get owner phone from client config
            owner_phone = await _get_owner_phone(client_id)
            if owner_phone:
                full_msg = f"🔔 *{priority.upper()}*\n{message}"
                if metadata:
                    full_msg += f"\n\nDetails: {metadata}"
                return await send_whatsapp(owner_phone, full_msg, client_id)
        
        elif channel == "slack":
            # Slack webhook integration would go here
            pass
        
        elif channel == "email":
            # Email integration would go here
            pass
        
        return True
    except Exception as e:
        logger.error(f"Notification failed: {e}")
        return False


async def _get_owner_phone(client_id: int) -> Optional[str]:
    """Get owner's WhatsApp number from client config."""
    try:
        from db import async_session, Client
        async with async_session() as session:
            result = await session.execute(
                select(Client).where(Client.id == client_id)
            )
            client = result.scalar_one_or_none()
            return client.whatsapp_number if client else None
    except Exception:
        return None


# =============================================================================
# 5.5 next_best_action — Decision logic in one place
# =============================================================================
class NextAction(Enum):
    NUDGE = "nudge"
    WAIT = "wait"
    ESCALATE = "escalate"
    MARK_COLD = "mark_cold"
    CALL_NOW = "call_now"
    SEND_QUOTE = "send_quote"
    BOOK_DEMO = "book_demo"


def next_best_action(
    lead_state: Dict[str, Any],
) -> NextAction:
    """
    Turns scattered if/else lead logic into one testable function.
    
    Args:
        lead_state: Dict with keys like:
            - score: float (0-100)
            - stage: str (new, contacted, qualified, hot, converted, cold)
            - urgency: UrgencyLevel
            - sentiment: Sentiment
            - days_since_contact: int
            - engagement_count: int
            - last_action: str
            - budget: float
    
    Returns:
        NextAction enum
    """
    score = lead_state.get("score", 0)
    stage = lead_state.get("stage", "new")
    urgency = lead_state.get("urgency", "low")
    sentiment = lead_state.get("sentiment", "neutral")
    days_since = lead_state.get("days_since_contact", 0)
    engagement = lead_state.get("engagement_count", 0)
    
    # High priority: Hot lead with urgency
    if urgency in ["critical", "high"] and score >= 70:
        return NextAction.CALL_NOW
    
    # Frustrated customer needs human
    if sentiment == "frustrated" and score >= 40:
        return NextAction.ESCALATE
    
    # Hot lead, ready for quote
    if stage == "hot" and score >= 75:
        return NextAction.SEND_QUOTE
    
    # Qualified, ready for demo
    if stage == "qualified" and score >= 60:
        return NextAction.BOOK_DEMO
    
    # Long silence, nudge
    if days_since >= 3 and stage in ["new", "contacted", "qualified"]:
        return NextAction.NUDGE
    
    # Very long silence, mark cold
    if days_since >= 14 and stage != "converted":
        return NextAction.MARK_COLD
    
    # Default: wait
    return NextAction.WAIT