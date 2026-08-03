"""
AI-driven Lead Scoring Engine — scores leads based on behavior, demographics, and engagement
"""
import json
import logging
import math
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("lead_scoring")


class LeadTier(Enum):
    HOT = "hot"        # Ready to buy — immediate follow-up
    WARM = "warm"      # Interested — nurture
    COLD = "cold"      # Low interest — long-term nurture
    DEAD = "dead"      # Unresponsive — archive


class LeadSignal(Enum):
    """Signals that affect lead score"""
    MESSAGE_REPLY = "message_reply"
    LINK_CLICK = "link_click"
    PRICE_QUERY = "price_query"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_NO_SHOW = "appointment_no_show"
    DOCUMENT_UPLOAD = "document_upload"
    WEBSITE_VISIT = "website_visit"
    FORM_SUBMISSION = "form_submission"
    SOCIAL_MEDIA_CLICK = "social_media_click"
    UNSUBSCRIBE = "unsubscribe"
    COMPLAINT = "complaint"
    POSITIVE_FEEDBACK = "positive_feedback"
    NEGATIVE_FEEDBACK = "negative_feedback"
    REFERRAL_MADE = "referral_made"
    PURCHASE_MADE = "purchase_made"
    CUSTOM_EVENT = "custom_event"


# Signal weights — how much each signal affects the score
SIGNAL_WEIGHTS = {
    LeadSignal.MESSAGE_REPLY: 5,
    LeadSignal.LINK_CLICK: 3,
    LeadSignal.PRICE_QUERY: 15,
    LeadSignal.APPOINTMENT_BOOKED: 25,
    LeadSignal.APPOINTMENT_NO_SHOW: -20,
    LeadSignal.DOCUMENT_UPLOAD: 10,
    LeadSignal.WEBSITE_VISIT: 2,
    LeadSignal.FORM_SUBMISSION: 8,
    LeadSignal.SOCIAL_MEDIA_CLICK: 2,
    LeadSignal.UNSUBSCRIBE: -30,
    LeadSignal.COMPLAINT: -25,
    LeadSignal.POSITIVE_FEEDBACK: 10,
    LeadSignal.NEGATIVE_FEEDBACK: -15,
    LeadSignal.REFERRAL_MADE: 30,
    LeadSignal.PURCHASE_MADE: 50,
    LeadSignal.CUSTOM_EVENT: 5,
}


class LeadProfile:
    """Tracks a lead's profile and score over time"""

    def __init__(self, contact_id: str, client_id: int = 1):
        self.contact_id = contact_id
        self.client_id = client_id
        self.score: float = 0.0
        self.tier: LeadTier = LeadTier.COLD
        self.signals: List[Dict] = []
        self.tags: List[str] = []
        self.custom_fields: Dict[str, Any] = {}
        self.first_seen: str = datetime.utcnow().isoformat()
        self.last_active: str = datetime.utcnow().isoformat()
        self.total_messages: int = 0
        self.total_replies: int = 0
        self.conversation_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "contact_id": self.contact_id,
            "client_id": self.client_id,
            "score": round(self.score, 1),
            "tier": self.tier.value,
            "signals": self.signals[-20:],  # last 20 signals
            "tags": self.tags,
            "custom_fields": self.custom_fields,
            "first_seen": self.first_seen,
            "last_active": self.last_active,
            "total_messages": self.total_messages,
            "total_replies": self.total_replies,
            "conversation_count": self.conversation_count,
        }


class LeadScoringEngine:
    """
    AI-driven lead scoring engine.
    Scores are calculated from:
    - Signal weights (behavioral)
    - Recency factor (recent activity = higher weight)
    - Engagement ratio (replies / messages)
    - Custom field boosts (e.g., budget > 1L = +20)
    """

    def __init__(self):
        self.profiles: Dict[str, LeadProfile] = {}  # key: f"{client_id}_{contact_id}"

    def _get_key(self, contact_id: str, client_id: int) -> str:
        return f"{client_id}_{contact_id}"

    def get_profile(self, contact_id: str, client_id: int = 1) -> LeadProfile:
        """Get or create a lead profile"""
        key = self._get_key(contact_id, client_id)
        if key not in self.profiles:
            self.profiles[key] = LeadProfile(contact_id, client_id)
        return self.profiles[key]

    def record_signal(self, contact_id: str, signal: LeadSignal,
                      client_id: int = 1, metadata: Optional[Dict] = None):
        """Record a signal and recalculate score"""
        profile = self.get_profile(contact_id, client_id)
        now = datetime.utcnow()

        # Update activity metrics
        profile.last_active = now.isoformat()
        profile.total_messages += 1
        if signal == LeadSignal.MESSAGE_REPLY:
            profile.total_replies += 1

        # Record signal
        signal_entry = {
            "signal": signal.value,
            "timestamp": now.isoformat(),
            "weight": SIGNAL_WEIGHTS.get(signal, 0),
            "metadata": metadata or {},
        }
        profile.signals.append(signal_entry)

        # Recalculate score
        self._recalculate(profile)

    def _recalculate(self, profile: LeadProfile):
        """Recalculate lead score based on all signals and factors"""
        now = datetime.utcnow()
        total_score = 0.0

        # 1. Signal-based scoring (with recency decay)
        for entry in profile.signals:
            signal_time = datetime.fromisoformat(entry["timestamp"])
            hours_ago = (now - signal_time).total_seconds() / 3600

            # Recency factor: signals within 24h get full weight, decays logarithmically
            recency_factor = max(0.1, 1.0 - (math.log2(hours_ago + 1) / 10))
            weight = entry["weight"]
            total_score += weight * recency_factor

        # 2. Engagement ratio bonus
        if profile.total_messages > 0:
            engagement_ratio = profile.total_replies / profile.total_messages
            total_score += engagement_ratio * 20  # up to +20 points

        # 3. Conversation count bonus
        total_score += min(profile.conversation_count * 2, 15)  # max +15

        # 4. Custom field boosts
        budget = profile.custom_fields.get("budget", 0)
        if isinstance(budget, (int, float)) and budget > 100000:
            total_score += 20
        elif isinstance(budget, (int, float)) and budget > 50000:
            total_score += 10

        location = profile.custom_fields.get("location", "")
        if location and location.lower() in profile.custom_fields.get("target_locations", []):
            total_score += 10

        # Normalize to 0-100
        profile.score = max(0, min(100, total_score))

        # Determine tier
        if profile.score >= 60:
            profile.tier = LeadTier.HOT
        elif profile.score >= 30:
            profile.tier = LeadTier.WARM
        elif profile.score >= 10:
            profile.tier = LeadTier.COLD
        else:
            profile.tier = LeadTier.DEAD

    def update_custom_fields(self, contact_id: str, fields: Dict[str, Any],
                             client_id: int = 1):
        """Update custom fields and recalculate"""
        profile = self.get_profile(contact_id, client_id)
        profile.custom_fields.update(fields)
        self._recalculate(profile)

    def add_tag(self, contact_id: str, tag: str, client_id: int = 1):
        """Add a tag to a lead"""
        profile = self.get_profile(contact_id, client_id)
        if tag not in profile.tags:
            profile.tags.append(tag)

    def remove_tag(self, contact_id: str, tag: str, client_id: int = 1):
        """Remove a tag from a lead"""
        profile = self.get_profile(contact_id, client_id)
        if tag in profile.tags:
            profile.tags.remove(tag)

    def get_leads_by_tier(self, tier: LeadTier, client_id: int = 1) -> List[LeadProfile]:
        """Get all leads in a specific tier"""
        return [
            p for p in self.profiles.values()
            if p.client_id == client_id and p.tier == tier
        ]

    def get_leads_by_tag(self, tag: str, client_id: int = 1) -> List[LeadProfile]:
        """Get all leads with a specific tag"""
        return [
            p for p in self.profiles.values()
            if p.client_id == client_id and tag in p.tags
        ]

    def get_top_leads(self, limit: int = 10, client_id: int = 1) -> List[LeadProfile]:
        """Get highest-scoring leads"""
        leads = [p for p in self.profiles.values() if p.client_id == client_id]
        leads.sort(key=lambda x: x.score, reverse=True)
        return leads[:limit]

    def get_stats(self, client_id: int = 1) -> Dict:
        """Get scoring statistics"""
        leads = [p for p in self.profiles.values() if p.client_id == client_id]
        return {
            "total_leads": len(leads),
            "hot": sum(1 for p in leads if p.tier == LeadTier.HOT),
            "warm": sum(1 for p in leads if p.tier == LeadTier.WARM),
            "cold": sum(1 for p in leads if p.tier == LeadTier.COLD),
            "dead": sum(1 for p in leads if p.tier == LeadTier.DEAD),
            "avg_score": round(sum(p.score for p in leads) / max(len(leads), 1), 1),
        }


# Global engine instance
scoring_engine = LeadScoringEngine()