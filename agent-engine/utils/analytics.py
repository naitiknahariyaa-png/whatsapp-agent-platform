"""
Analytics & Observability Functions
Turn raw events into actionable business intelligence.
"""
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# 9.1 track_event — Central event bus
# ---------------------------------------------------------------------------
@dataclass
class AnalyticsEvent:
    event_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    client_id: int = 1
    user_id: Optional[str] = None
    session_id: Optional[str] = None


async def track_event(
    event_type: str,
    properties: Optional[Dict[str, Any]] = None,
    client_id: int = 1,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> bool:
    """
    Central event bus for analytics.
    All conversion events flow through here for funnel reports.

    Args:
        event_type: Event name (e.g., "message_sent", "lead_created", "payment_completed")
        properties: Event metadata
        client_id: Business client ID
        user_id: Optional user identifier
        session_id: Optional session identifier

    Returns:
        True if tracked successfully
    """
    event = AnalyticsEvent(
        event_type=event_type,
        properties=properties or {},
        client_id=client_id,
        user_id=user_id,
        session_id=session_id,
    )

    try:
        r = _get_redis()
        key = f"analytics:event:{client_id}:{datetime.utcnow().strftime('%Y%m%d')}"
        await r.rpush(key, json.dumps({
            "event_type": event.event_type,
            "properties": event.properties,
            "timestamp": event.timestamp.isoformat(),
            "user_id": event.user_id,
            "session_id": event.session_id,
        }))
        # Set TTL to 90 days
        await r.expire(key, 90 * 24 * 3600)
        return True
    except Exception as e:
        logger.error(f"Failed to track event {event_type}: {e}")
        return False


# ---------------------------------------------------------------------------
# 9.2 funnel_dropoff_report — See where leads leave
# ---------------------------------------------------------------------------
@dataclass
class FunnelStage:
    name: str
    count: int = 0
    dropoff: int = 0


async def funnel_dropoff_report(
    client_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Calculates drop-off at each funnel stage.
    Surfaces the exact step where leads lose interest.

    Args:
        client_id: Business client ID
        start_date: Report start date
        end_date: Report end date

    Returns:
        Funnel report with stages, counts, and dropoff rates
    """
    if start_date is None:
        start_date = datetime.utcnow() - timedelta(days=30)
    if end_date is None:
        end_date = datetime.utcnow()

    stages = [
        FunnelStage("messages_received"),
        FunnelStage("leads_created"),
        FunnelStage("appointments_booked"),
        FunnelStage("payments_completed"),
    ]

    try:
        r = _get_redis()
        date_range = []
        current = start_date.date()
        while current <= end_date.date():
            date_range.append(current.strftime('%Y%m%d'))
            current += timedelta(days=1)

        # Count events per stage
        for date_str in date_range:
            key = f"analytics:event:{client_id}:{date_str}"
            events = await r.lrange(key, 0, -1)
            for event_data in events:
                try:
                    event = json.loads(event_data)
                    event_type = event.get("event_type", "")
                    for stage in stages:
                        if stage.name == event_type:
                            stage.count += 1
                            break
                except json.JSONDecodeError:
                    continue

        # Calculate dropoff
        result = []
        prev_count = None
        for stage in stages:
            if prev_count is not None:
                stage.dropoff = prev_count - stage.count
            conversion_rate = 0.0
            if stages[0].count > 0:
                conversion_rate = (stage.count / stages[0].count) * 100
            result.append({
                "stage": stage.name,
                "count": stage.count,
                "dropoff": stage.dropoff,
                "conversion_rate": round(conversion_rate, 1),
            })
            prev_count = stage.count

        return {
            "client_id": client_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "stages": result,
            "total_events": sum(s.count for s in stages),
        }

    except Exception as e:
        logger.error(f"Funnel report failed: {e}")
        return {"error": str(e), "client_id": client_id}


# ---------------------------------------------------------------------------
# 9.3 average_response_time — Latency benchmark
# ---------------------------------------------------------------------------
class ResponseTimeTracker:
    """Tracks response times for SLA monitoring."""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def record(self, client_id: int, latency_seconds: float):
        key = f"client:{client_id}"
        self._times[key].append(latency_seconds)

    def average(self, client_id: int) -> float:
        key = f"client:{client_id}"
        times = list(self._times[key])
        if not times:
            return 0.0
        return sum(times) / len(times)

    def percentile(self, client_id: int, p: float = 0.95) -> float:
        key = f"client:{client_id}"
        times = sorted(self._times[key])
        if not times:
            return 0.0
        idx = int(len(times) * p)
        return times[min(idx, len(times) - 1)]


_response_tracker = ResponseTimeTracker()


async def average_response_time(
    client_id: int,
    period: str = "day",  # day, week, month
) -> Dict[str, Any]:
    """
    Calculate average and percentile response times.

    Args:
        client_id: Business client ID
        period: Time period for aggregation

    Returns:
        Response time statistics
    """
    if period == "day":
        since = datetime.utcnow() - timedelta(days=1)
    elif period == "week":
        since = datetime.utcnow() - timedelta(weeks=1)
    elif period == "month":
        since = datetime.utcnow() - timedelta(days=30)
    else:
        since = datetime.utcnow() - timedelta(days=1)

    try:
        r = _get_redis()
        latencies = []
        current = since.date()
        end = datetime.utcnow().date()
        while current <= end:
            date_str = current.strftime('%Y%m%d')
            key = f"analytics:latency:{client_id}:{date_str}"
            values = await r.lrange(key, 0, -1)
            for v in values:
                try:
                    latencies.append(float(v))
                except ValueError:
                    continue
            current += timedelta(days=1)

        if not latencies:
            return {
                "client_id": client_id,
                "period": period,
                "average_seconds": 0.0,
                "p95_seconds": 0.0,
                "sample_count": 0,
            }

        latencies.sort()
        avg = sum(latencies) / len(latencies)
        p95_idx = int(len(latencies) * 0.95)

        return {
            "client_id": client_id,
            "period": period,
            "average_seconds": round(avg, 3),
            "p95_seconds": round(latencies[min(p95_idx, len(latencies) - 1)], 3),
            "min_seconds": round(min(latencies), 3),
            "max_seconds": round(max(latencies), 3),
            "sample_count": len(latencies),
        }

    except Exception as e:
        logger.error(f"Response time calculation failed: {e}")
        return {"error": str(e), "client_id": client_id}


def record_latency(client_id: int, latency_seconds: float):
    """Record a single latency sample."""
    try:
        r = _get_redis()
        date_str = datetime.utcnow().strftime('%Y%m%d')
        key = f"analytics:latency:{client_id}:{date_str}"
        r.rpush(key, str(latency_seconds))
        r.expire(key, 90 * 24 * 3600)
        _response_tracker.record(client_id, latency_seconds)
    except Exception as e:
        logger.error(f"Failed to record latency: {e}")


# ---------------------------------------------------------------------------
# 9.4 most_asked_questions — FAQ discovery
# ---------------------------------------------------------------------------
@dataclass
class QuestionFrequency:
    question: str
    count: int = 0
    last_asked: Optional[str] = None


async def most_asked_questions(
    client_id: int,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """
    Extract and rank most frequent user questions.
    Feed this directly into your FAQ / knowledge base.

    Args:
        client_id: Business client ID
        start_date: Report start date
        end_date: Report end date
        top_n: Number of top questions to return

    Returns:
        List of {question, count, last_asked} dicts
    """
    if start_date is None:
        start_date = datetime.utcnow() - timedelta(days=30)
    if end_date is None:
        end_date = datetime.utcnow()

    question_counts: Dict[str, QuestionFrequency] = {}

    try:
        r = _get_redis()
        current = start_date.date()
        end = end_date.date()
        while current <= end:
            date_str = current.strftime('%Y%m%d')
            key = f"analytics:questions:{client_id}:{date_str}"
            questions = await r.lrange(key, 0, -1)
            for q in questions:
                q = q.strip()
                if not q:
                    continue
                if q not in question_counts:
                    question_counts[q] = QuestionFrequency(question=q)
                question_counts[q].count += 1
                question_counts[q].last_asked = current.isoformat()
            current += timedelta(days=1)

        ranked = sorted(question_counts.values(), key=lambda x: x.count, reverse=True)
        return [
            {"question": q.question, "count": q.count, "last_asked": q.last_asked}
            for q in ranked[:top_n]
        ]

    except Exception as e:
        logger.error(f"Most asked questions failed: {e}")
        return []


async def track_question(client_id: int, question: str):
    """Track a user question for frequency analysis."""
    try:
        r = _get_redis()
        date_str = datetime.utcnow().strftime('%Y%m%d')
        key = f"analytics:questions:{client_id}:{date_str}"
        await r.rpush(key, question)
        await r.expire(key, 90 * 24 * 3600)
    except Exception as e:
        logger.error(f"Failed to track question: {e}")
