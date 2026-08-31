"""
Usage-Based Billing Hooks
=========================

Meters tokens, messages, API calls per client from day one.
Foundation for usage-based billing, quotas, and cost management.

Features:
- Per-tenant usage tracking (messages, tokens, API calls, leads, appointments)
- Real-time quota enforcement
- Daily/monthly rollups
- Webhook notifications for billing systems
- Export for invoicing
- Cost estimation per action
"""
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from collections import defaultdict

logger = logging.getLogger("usage_metering")


class MetricType(Enum):
    """Types of billable metrics."""
    MESSAGES_INBOUND = "messages_inbound"
    MESSAGES_RECEIVED = "messages_received"
    MESSAGES_OUTBOUND = "messages_outbound"
    MESSAGES_SENT = "messages_sent"
    TOKENS_PROMPT = "tokens_prompt"
    TOKENS_COMPLETION = "tokens_completion"
    TOKENS_USED = "tokens_used"
    LLM_CALLS = "llm_calls"
    TOOL_CALLS = "tool_calls"
    LEADS_PROCESSED = "leads_processed"
    APPOINTMENTS_BOOKED = "appointments_booked"
    API_REQUESTS = "api_requests"
    APPROVAL_REQUESTS = "approval_requests"
    VECTOR_SEARCH = "vector_search"
    DOCUMENT_INGESTED = "document_ingested"
    AUDIO_TRANSCRIBED = "audio_transcribed"
    IMAGE_ANALYZED = "image_analyzed"


class BillingPeriod(Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class UsageRecord:
    """A single usage record."""
    client_id: int
    metric: MetricType
    quantity: int = 1
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    cost_usd: float = 0.0


@dataclass
class ClientQuota:
    """Quota configuration for a client."""
    client_id: int
    plan: str = "trial"  # trial, basic, pro, enterprise
    limits: Dict[MetricType, int] = field(default_factory=dict)
    current_usage: Dict[MetricType, int] = field(default_factory=dict)
    billing_period: BillingPeriod = BillingPeriod.MONTHLY
    period_start: str = field(default_factory=lambda: datetime.utcnow().replace(day=1).isoformat())
    overage_policy: str = "block"  # block, allow, bill
    alert_thresholds: List[float] = field(default_factory=lambda: [0.5, 0.8, 0.95])
    alert_sent: List[float] = field(default_factory=list)


@dataclass
class UsageSummary:
    """Aggregated usage for a period."""
    client_id: int
    period: BillingPeriod
    period_start: str
    period_end: str
    totals: Dict[MetricType, int] = field(default_factory=dict)
    costs: Dict[MetricType, float] = field(default_factory=dict)
    total_cost_usd: float = 0.0


# ─── Default Plan Limits ──────────────────────────────────────────

DEFAULT_PLAN_LIMITS = {
    "trial": {
        MetricType.MESSAGES_INBOUND: 100,
        MetricType.MESSAGES_OUTBOUND: 100,
        MetricType.TOKENS_PROMPT: 50000,
        MetricType.TOKENS_COMPLETION: 25000,
        MetricType.LLM_CALLS: 200,
        MetricType.LEADS_PROCESSED: 10,
        MetricType.APPOINTMENTS_BOOKED: 5,
        MetricType.API_REQUESTS: 1000,
        MetricType.APPROVAL_REQUESTS: 5,
        MetricType.VECTOR_SEARCH: 50,
        MetricType.DOCUMENT_INGESTED: 5,
    },
    "basic": {
        MetricType.MESSAGES_INBOUND: 5000,
        MetricType.MESSAGES_OUTBOUND: 5000,
        MetricType.TOKENS_PROMPT: 2000000,
        MetricType.TOKENS_COMPLETION: 1000000,
        MetricType.LLM_CALLS: 10000,
        MetricType.LEADS_PROCESSED: 200,
        MetricType.APPOINTMENTS_BOOKED: 100,
        MetricType.API_REQUESTS: 50000,
        MetricType.APPROVAL_REQUESTS: 50,
        MetricType.VECTOR_SEARCH: 1000,
        MetricType.DOCUMENT_INGESTED: 50,
    },
    "pro": {
        MetricType.MESSAGES_INBOUND: 50000,
        MetricType.MESSAGES_OUTBOUND: 50000,
        MetricType.TOKENS_PROMPT: 20000000,
        MetricType.TOKENS_COMPLETION: 10000000,
        MetricType.LLM_CALLS: 100000,
        MetricType.LEADS_PROCESSED: 2000,
        MetricType.APPOINTMENTS_BOOKED: 1000,
        MetricType.API_REQUESTS: 500000,
        MetricType.APPROVAL_REQUESTS: 500,
        MetricType.VECTOR_SEARCH: 10000,
        MetricType.DOCUMENT_INGESTED: 500,
    },
    "enterprise": {
        MetricType.MESSAGES_INBOUND: -1,  # Unlimited
        MetricType.MESSAGES_OUTBOUND: -1,
        MetricType.TOKENS_PROMPT: -1,
        MetricType.TOKENS_COMPLETION: -1,
        MetricType.LLM_CALLS: -1,
        MetricType.LEADS_PROCESSED: -1,
        MetricType.APPOINTMENTS_BOOKED: -1,
        MetricType.API_REQUESTS: -1,
        MetricType.APPROVAL_REQUESTS: -1,
        MetricType.VECTOR_SEARCH: -1,
        MetricType.DOCUMENT_INGESTED: -1,
    },
}


# ─── Token Cost Estimates ──────────────────────────────────────────

MODEL_COST_PER_1K = {
    "llama-3.1-8b-instant": {"prompt": 0.05, "completion": 0.08},
    "llama-3.3-70b-versatile": {"prompt": 0.59, "completion": 0.79},
    "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    "gpt-4o": {"prompt": 5.00, "completion": 15.00},
    "ollama": {"prompt": 0.0, "completion": 0.0},  # Local
}


# ─── Usage Meter ──────────────────────────────────────────────────

class UsageMeter:
    """
    Tracks and meters usage per client with quota enforcement.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/3",
        webhook_url: Optional[str] = None,
    ):
        self.redis_url = redis_url
        self.webhook_url = webhook_url
        self._redis = None
        self._local_usage: Dict[int, Dict[MetricType, int]] = defaultdict(lambda: defaultdict(int))
        self._quotas: Dict[int, ClientQuota] = {}
        self._hooks: List[Callable[[UsageRecord], None]] = []
        self._init_redis()

    def _init_redis(self):
        try:
            import redis
            self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
            self._redis.ping()
            logger.info("Usage meter connected to Redis")
        except Exception as e:
            logger.warning("Redis not available for usage metering: %s", e)
            self._redis = None

    def register_hook(self, hook: Callable[[UsageRecord], None]):
        """Register a webhook/callback for each usage record."""
        self._hooks.append(hook)

    async def record(
        self,
        client_id: int,
        metric: MetricType,
        quantity: int = 1,
        trace_id: str = None,
        metadata: Dict[str, Any] = None,
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> Dict[str, Any]:
        """
        Record a usage event. Returns quota check result.
        """
        # Check quota first
        quota_check = await self._check_quota(client_id, metric, quantity)
        if not quota_check["allowed"]:
            return quota_check

        # Calculate cost
        cost = self._estimate_cost(metric, quantity, model, prompt_tokens, completion_tokens)

        # Create record
        record = UsageRecord(
            client_id=client_id,
            metric=metric,
            quantity=quantity,
            timestamp=datetime.utcnow().isoformat(),
            metadata=metadata or {},
            trace_id=trace_id,
            cost_usd=cost,
        )

        # Store record
        await self._store_record(record)

        # Update quota
        await self._increment_usage(client_id, metric, quantity, cost)

        # Fire hooks
        for hook in self._hooks:
            try:
                hook(record)
            except Exception as e:
                logger.warning("Usage hook failed: %s", e)

        # Send webhook if configured
        if self.webhook_url:
            await self._send_webhook(record)

        return {
            "allowed": True,
            "usage": self.get_current_usage(client_id),
            "quota_remaining": await self.get_quota_remaining(client_id),
        }

    async def _check_quota(self, client_id: int, metric: MetricType, quantity: int) -> Dict[str, Any]:
        """Check if usage would exceed quota."""
        quota = await self.get_quota(client_id)
        limit = quota.limits.get(metric, -1)
        if limit == -1:  # Unlimited
            return {"allowed": True}

        current = quota.current_usage.get(metric, 0)
        if current + quantity > limit:
            return {
                "allowed": False,
                "reason": f"Quota exceeded for {metric.value}",
                "limit": limit,
                "current": current,
                "requested": quantity,
                "overage_policy": quota.overage_policy,
            }
        return {"allowed": True}

    async def get_quota(self, client_id: int) -> ClientQuota:
        """Get or create quota for client."""
        if client_id in self._quotas:
            return self._quotas[client_id]

        # Try to load from Redis
        if self._redis:
            try:
                data = self._redis.get(f"quota:{client_id}")
                if data:
                    q = ClientQuota(**json.loads(data))
                    self._quotas[client_id] = q
                    return q
            except Exception:
                pass

        # Create default quota
        quota = ClientQuota(
            client_id=client_id,
            plan="trial",
            limits=DEFAULT_PLAN_LIMITS.get("trial", {}),
            billing_period=BillingPeriod.MONTHLY,
            period_start=datetime.utcnow().replace(day=1).isoformat(),
        )
        self._quotas[client_id] = quota
        await self._save_quota(quota)
        return quota

    async def set_quota(self, quota: ClientQuota):
        """Set/update quota for a client."""
        self._quotas[quota.client_id] = quota
        await self._save_quota(quota)

    async def _save_quota(self, quota: ClientQuota):
        if self._redis:
            try:
                self._redis.set(f"quota:{quota.client_id}", json.dumps(asdict(quota), default=str))
            except Exception as e:
                logger.warning("Failed to save quota: %s", e)

    async def _increment_usage(self, client_id: int, metric: MetricType, quantity: int, cost: float):
        """Increment usage counters."""
        key = f"usage:{client_id}:{datetime.utcnow().strftime('%Y%m')}"
        if self._redis:
            try:
                pipe = self._redis.pipeline()
                pipe.hincrby(key, metric.value, quantity)
                pipe.hincrbyfloat(key, f"{metric.value}_cost", cost)
                pipe.expire(key, 86400 * 40)  # Keep for ~40 days
                pipe.execute()
            except Exception:
                pass

        self._local_usage[client_id][metric] += quantity

    async def _store_record(self, record: UsageRecord):
        if self._redis:
            try:
                key = f"usage_log:{record.client_id}:{datetime.utcnow().strftime('%Y%m%d')}"
                self._redis.rpush(key, json.dumps(asdict(record), default=str))
                self._redis.expire(key, 86400 * 90)  # 90 days
            except Exception:
                pass

    def get_current_usage(self, client_id: int) -> Dict[MetricType, int]:
        """Get current period usage for a client."""
        usage = dict(self._local_usage.get(client_id, {}))
        if self._redis:
            try:
                key = f"usage:{client_id}:{datetime.utcnow().strftime('%Y%m')}"
                data = self._redis.hgetall(key)
                for k, v in data.items():
                    try:
                        usage[MetricType(k)] = int(v)
                    except ValueError:
                        pass
            except Exception:
                pass
        return usage

    def get_usage(self, client_id: int) -> Dict[str, int]:
        """Alias for get_current_usage (backward compatibility) with string keys."""
        usage = self.get_current_usage(client_id)
        return {k.value if hasattr(k, 'value') else str(k): v for k, v in usage.items()}

    async def get_quota_remaining(self, client_id: int) -> Dict[str, int]:
        """Get remaining quota for all metrics."""
        quota = await self.get_quota(client_id)
        current = self.get_current_usage(client_id)
        remaining = {}
        for metric, limit in quota.limits.items():
            if limit == -1:
                remaining[metric.value] = -1
            else:
                remaining[metric.value] = max(0, limit - current.get(metric, 0))
        return remaining

    async def get_summary(self, client_id: int, period: BillingPeriod = BillingPeriod.MONTHLY) -> UsageSummary:
        """Get usage summary for billing."""
        # Simplified - in production would aggregate from logs
        usage = await self.get_current_usage(client_id)
        costs = {}
        total = 0.0
        for metric, qty in usage.items():
            cost = self._estimate_cost(metric, qty)
            costs[metric] = cost
            total += cost

        return UsageSummary(
            client_id=client_id,
            period=period,
            period_start=datetime.utcnow().replace(day=1).isoformat(),
            period_end=datetime.utcnow().isoformat(),
            totals=usage,
            costs=costs,
            total_cost_usd=total,
        )

    def _estimate_cost(self, metric: MetricType, quantity: int, model: str = "", prompt_tokens: int = 0, completion_tokens: int = 0) -> float:
        if metric in (MetricType.TOKENS_PROMPT, MetricType.TOKENS_COMPLETION):
            if not model or model not in MODEL_COST_PER_1K:
                return 0.0
            pricing = MODEL_COST_PER_1K[model]
            if metric == MetricType.TOKENS_PROMPT:
                return (quantity / 1000) * pricing["prompt"]
            else:
                return (quantity / 1000) * pricing["completion"]
        # Fixed costs for other metrics
        fixed_costs = {
            MetricType.LEADS_PROCESSED: 0.01,
            MetricType.APPOINTMENTS_BOOKED: 0.02,
            MetricType.APPROVAL_REQUESTS: 0.005,
            MetricType.VECTOR_SEARCH: 0.001,
            MetricType.DOCUMENT_INGESTED: 0.01,
        }
        return fixed_costs.get(metric, 0.0) * quantity

    async def _send_webhook(self, record: UsageRecord):
        if not self.webhook_url:
            return
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(self.webhook_url, json=asdict(record), timeout=5)
        except Exception as e:
            logger.warning("Usage webhook failed: %s", e)

    def add_hook(self, hook: Callable[[UsageRecord], None]):
        self._hooks.append(hook)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "clients_tracked": len(self._local_usage),
            "total_metrics": sum(len(v) for v in self._local_usage.values()),
        }

    def reset_memory(self):
        """Reset in-memory usage stores (for testing)."""
        self._local_usage.clear()
        self._quotas.clear()
        self._hooks.clear()
        if self._redis:
            try:
                # Clear Redis keys for this test
                for key in self._redis.scan_iter("usage:*"):
                    self._redis.delete(key)
                for key in self._redis.scan_iter("quota:*"):
                    self._redis.delete(key)
                for key in self._redis.scan_iter("usage_log:*"):
                    self._redis.delete(key)
            except Exception:
                pass

    async def record_usage(self, client_id: int, metric: str, quantity: int = 1, **kwargs) -> Dict[str, Any]:
        """Alias for record() with string metric."""
        try:
            m = MetricType(metric)
        except ValueError:
            m = MetricType.MESSAGES_INBOUND
        return await self.record(client_id, m, quantity, **kwargs)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "clients_tracked": len(self._local_usage),
            "total_metrics": sum(len(v) for v in self._local_usage.values()),
        }


# ─── Global Instance ──────────────────────────────────────────────

usage_meter = UsageMeter()


# ─── Integration Helpers ───────────────────────────────────────────

async def record_usage(
    client_id: int,
    metric: MetricType,
    quantity: int = 1,
    **kwargs,
) -> Dict[str, Any]:
    """Quick helper to record usage."""
    return await usage_meter.record(client_id, metric, quantity, **kwargs)


async def check_quota(client_id: int, metric: MetricType, quantity: int = 1) -> Dict[str, Any]:
    """Quick quota check."""
    return await usage_meter._check_quota(client_id, metric, quantity)


async def get_client_usage(client_id: int) -> Dict[MetricType, int]:
    return usage_meter.get_current_usage(client_id)


async def get_client_summary(client_id: int, period: BillingPeriod = BillingPeriod.MONTHLY) -> UsageSummary:
    return await usage_meter.get_summary(client_id, period)


# ─── Webhook Handler for External Billing Systems ──────────────────

async def usage_webhook_handler(request):
    """Handle incoming usage webhooks (for external systems)."""
    # This would be a FastAPI endpoint
    pass


def get_usage_meter() -> UsageMeter:
    return usage_meter