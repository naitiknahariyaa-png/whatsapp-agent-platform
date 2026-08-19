"""
Analytics Service — Track message events and generate reports
"""
import os
import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("analytics")


class MessageStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    REPLIED = "replied"


@dataclass
class MessageEvent:
    """A single message lifecycle event"""
    id: str
    client_id: int
    phone_number: str
    direction: str  # outbound, inbound
    message_type: str  # template, free_text, media
    template_id: Optional[str] = None
    campaign_id: Optional[str] = None
    status: MessageStatus = MessageStatus.QUEUED
    wamid: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    sent_at: Optional[str] = None
    delivered_at: Optional[str] = None
    read_at: Optional[str] = None
    replied_at: Optional[str] = None
    cost: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "phone_number": self.phone_number,
            "direction": self.direction,
            "message_type": self.message_type,
            "template_id": self.template_id,
            "campaign_id": self.campaign_id,
            "status": self.status.value,
            "wamid": self.wamid,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "sent_at": self.sent_at,
            "delivered_at": self.delivered_at,
            "read_at": self.read_at,
            "replied_at": self.replied_at,
            "cost": self.cost,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class DailyStats:
    """Aggregated daily statistics"""
    date: str
    client_id: int
    sent: int = 0
    delivered: int = 0
    read: int = 0
    failed: int = 0
    replied: int = 0
    unique_recipients: int = 0
    template_sends: int = 0
    free_text_sends: int = 0
    total_cost: float = 0.0


class AnalyticsEngine:
    """Track and analyze WhatsApp messaging performance"""

    def __init__(self):
        self.events: List[MessageEvent] = []
        self.daily_stats: Dict[str, DailyStats] = {}
        self._load_data()

    def _load_data(self):
        """Load analytics data from disk"""
        try:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "agent-engine", "data", "analytics")
            os.makedirs(data_dir, exist_ok=True)
            events_file = os.path.join(data_dir, "events.json")
            if os.path.exists(events_file):
                with open(events_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for e in data.get("events", []):
                        event = MessageEvent(
                            id=e["id"],
                            client_id=e["client_id"],
                            phone_number=e["phone_number"],
                            direction=e["direction"],
                            message_type=e.get("message_type", "free_text"),
                            template_id=e.get("template_id"),
                            campaign_id=e.get("campaign_id"),
                            status=MessageStatus(e.get("status", "queued")),
                            wamid=e.get("wamid"),
                            error_code=e.get("error_code"),
                            error_message=e.get("error_message"),
                            sent_at=e.get("sent_at"),
                            delivered_at=e.get("delivered_at"),
                            read_at=e.get("read_at"),
                            replied_at=e.get("replied_at"),
                            cost=e.get("cost"),
                            metadata=e.get("metadata", {}),
                            created_at=e.get("created_at", datetime.utcnow().isoformat()),
                        )
                        self.events.append(event)
                        self._update_daily_stats(event)
        except Exception as e:
            logger.warning(f"Failed to load analytics data: {e}")

    def _save_data(self):
        """Save analytics data to disk"""
        try:
            data_dir = os.path.join(os.path.dirname(__file__), "..", "agent-engine", "data", "analytics")
            os.makedirs(data_dir, exist_ok=True)
            events_file = os.path.join(data_dir, "events.json")
            data = {
                "events": [e.to_dict() for e in self.events]
            }
            with open(events_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save analytics data: {e}")

    def _update_daily_stats(self, event: MessageEvent):
        """Update daily statistics for an event"""
        date_key = event.created_at[:10] if event.created_at else datetime.utcnow().isoformat()[:10]
        if date_key not in self.daily_stats:
            self.daily_stats[date_key] = DailyStats(date=date_key, client_id=event.client_id)

        stats = self.daily_stats[date_key]
        if event.direction == "outbound":
            if event.status == MessageStatus.SENT:
                stats.sent += 1
            elif event.status == MessageStatus.DELIVERED:
                stats.delivered += 1
            elif event.status == MessageStatus.READ:
                stats.read += 1
            elif event.status == MessageStatus.FAILED:
                stats.failed += 1
            elif event.status == MessageStatus.REPLIED:
                stats.replied += 1

            if event.message_type == "template":
                stats.template_sends += 1
            else:
                stats.free_text_sends += 1

            if event.cost:
                stats.total_cost += event.cost

    def record_event(self, client_id: int, phone_number: str, direction: str,
                     message_type: str = "free_text", **kwargs) -> MessageEvent:
        """Record a new message event"""
        import uuid
        event = MessageEvent(
            id=str(uuid.uuid4())[:12],
            client_id=client_id,
            phone_number=phone_number,
            direction=direction,
            message_type=message_type,
            **kwargs
        )
        self.events.append(event)
        self._update_daily_stats(event)
        self._save_data()
        return event

    def update_event_status(self, event_id: str, status: MessageStatus,
                            timestamp: Optional[str] = None, **kwargs) -> Optional[MessageEvent]:
        """Update an event's status (e.g., delivered, read)"""
        event = next((e for e in self.events if e.id == event_id), None)
        if not event:
            return None

        event.status = status
        ts = timestamp or datetime.utcnow().isoformat()

        if status == MessageStatus.SENT:
            event.sent_at = ts
        elif status == MessageStatus.DELIVERED:
            event.delivered_at = ts
        elif status == MessageStatus.READ:
            event.read_at = ts
        elif status == MessageStatus.REPLIED:
            event.replied_at = ts
        elif status == MessageStatus.FAILED:
            event.error_code = kwargs.get("error_code")
            event.error_message = kwargs.get("error_message")

        for key, value in kwargs.items():
            if hasattr(event, key) and key not in ("status", "id"):
                setattr(event, key, value)

        self._save_data()
        return event

    def get_daily_stats(self, client_id: int, days: int = 7) -> List[Dict]:
        """Get daily stats for the last N days"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()[:10]
        stats = []
        for date_key, s in sorted(self.daily_stats.items()):
            if date_key >= cutoff and s.client_id == client_id:
                stats.append({
                    "date": s.date,
                    "sent": s.sent,
                    "delivered": s.delivered,
                    "read": s.read,
                    "failed": s.failed,
                    "replied": s.replied,
                    "delivery_rate": round(s.delivered / s.sent * 100, 1) if s.sent > 0 else 0,
                    "read_rate": round(s.read / s.delivered * 100, 1) if s.delivered > 0 else 0,
                    "reply_rate": round(s.replied / s.sent * 100, 1) if s.sent > 0 else 0,
                    "total_cost": round(s.total_cost, 2),
                })
        return stats

    def get_summary(self, client_id: int, days: int = 30) -> Dict[str, Any]:
        """Get overall summary statistics"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        client_events = [e for e in self.events if e.client_id == client_id and e.created_at >= cutoff]

        sent = sum(1 for e in client_events if e.direction == "outbound" and e.status in (MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ))
        delivered = sum(1 for e in client_events if e.status == MessageStatus.DELIVERED)
        read = sum(1 for e in client_events if e.status == MessageStatus.READ)
        failed = sum(1 for e in client_events if e.status == MessageStatus.FAILED)
        replied = sum(1 for e in client_events if e.status == MessageStatus.REPLIED)
        unique_phones = len(set(e.phone_number for e in client_events if e.direction == "outbound"))

        return {
            "period_days": days,
            "total_sent": sent,
            "total_delivered": delivered,
            "total_read": read,
            "total_failed": failed,
            "total_replied": replied,
            "unique_recipients": unique_phones,
            "delivery_rate": round(delivered / sent * 100, 1) if sent > 0 else 0,
            "read_rate": round(read / delivered * 100, 1) if delivered > 0 else 0,
            "reply_rate": round(replied / sent * 100, 1) if sent > 0 else 0,
            "failure_rate": round(failed / sent * 100, 1) if sent > 0 else 0,
        }

    def get_events(self, client_id: int, days: int = 7, status: Optional[str] = None) -> List[Dict]:
        """Get raw events for a client"""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        events = [e for e in self.events if e.client_id == client_id and e.created_at >= cutoff]
        if status:
            events = [e for e in events if e.status == status]
        return [e.to_dict() for e in events]


analytics = AnalyticsEngine()
