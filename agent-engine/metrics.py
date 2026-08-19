"""
Metrics collection for the WhatsApp Agent Platform.

Tracks (per-process and cluster-wide via Redis time-series buckets):
  - message_throughput      : messages/minute (minute buckets)
  - llm_latency             : p50 / p95 / p99 (hour buckets, capped sample lists)
  - tool_call_success_rate  : per tool + overall (day buckets)
  - funnel_drop_off_rates   : per funnel stage (day buckets)
  - error_rate by endpoint  : requests vs errors per endpoint (day buckets)

Storage: Redis when available, otherwise a bounded in-memory fallback so the
collector is always safe to call. Every public method swallows backend errors —
metrics must never break request handling.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional

from logging_setup import get_logger

logger = get_logger("metrics")

PREFIX = os.getenv("METRICS_KEY_PREFIX", "wap:metrics")

# Retention for the Redis buckets (seconds)
MINUTE_BUCKET_TTL = 2 * 60 * 60        # 2 hours of minute buckets
HOUR_BUCKET_TTL = 26 * 60 * 60         # ~1 day of hour buckets
DAY_BUCKET_TTL = 8 * 24 * 60 * 60      # 8 days of day buckets

MAX_LATENCY_SAMPLES = 2000             # per hour bucket

# Ordered lead-funnel stages used for drop-off computation
FUNNEL_STAGES: List[str] = [
    "new",
    "welcome_sent",
    "reminder_1_sent",
    "last_attempt_sent",
    "cold",
]


def _redis_client():
    """Return a sync Redis client or None (never raises)."""
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        client.ping()
        return client
    except Exception as e:  # pragma: no cover - depends on local env
        logger.info("Metrics falling back to in-memory store (redis unavailable: %s)", e)
        return None


def _minute_key(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H%M")


def _hour_key(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d%H")


def _day_key(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d")


def _percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile (pct between 0 and 100)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 2)
    rank = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return round(float(ordered[rank]), 2)


class _MemoryStore:
    """Bounded in-memory metric store used when Redis is unavailable."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: Dict[str, int] = defaultdict(int)
        self.hashes: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.lists: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=MAX_LATENCY_SAMPLES))

    def incr(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[key] += amount

    def hincr(self, key: str, field: str, amount: int = 1) -> None:
        with self._lock:
            self.hashes[key][field] += amount

    def push(self, key: str, value: float) -> None:
        with self._lock:
            self.lists[key].append(value)

    def get(self, key: str) -> int:
        with self._lock:
            return int(self.counters.get(key, 0))

    def hgetall(self, key: str) -> Dict[str, int]:
        with self._lock:
            return dict(self.hashes.get(key, {}))

    def lrange(self, key: str) -> List[float]:
        with self._lock:
            return list(self.lists.get(key, []))

    def reset(self) -> None:
        with self._lock:
            self.counters.clear()
            self.hashes.clear()
            self.lists.clear()


class MetricsCollector:
    """Collects platform metrics into Redis time-series buckets (or memory)."""

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client if redis_client is not None else _redis_client()
        self._memory = _MemoryStore()

    # -- backend helpers ----------------------------------------------------

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def _incr(self, key: str, ttl: int, amount: int = 1) -> None:
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incrby(key, amount)
                pipe.expire(key, ttl)
                pipe.execute()
                return
            except Exception as e:
                logger.debug("metrics incr failed (%s): %s", key, e)
        self._memory.incr(key, amount)

    def _hincr(self, key: str, field: str, ttl: int, amount: int = 1) -> None:
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.hincrby(key, field, amount)
                pipe.expire(key, ttl)
                pipe.execute()
                return
            except Exception as e:
                logger.debug("metrics hincr failed (%s.%s): %s", key, field, e)
        self._memory.hincr(key, field, amount)

    def _push(self, key: str, value: float, ttl: int) -> None:
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.lpush(key, value)
                pipe.ltrim(key, 0, MAX_LATENCY_SAMPLES - 1)
                pipe.expire(key, ttl)
                pipe.execute()
                return
            except Exception as e:
                logger.debug("metrics push failed (%s): %s", key, e)
        self._memory.push(key, value)

    def _get_int(self, key: str) -> int:
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                return int(raw) if raw is not None else 0
            except Exception:
                return 0
        return self._memory.get(key)

    def _get_hash(self, key: str) -> Dict[str, int]:
        if self._redis is not None:
            try:
                raw = self._redis.hgetall(key) or {}
                out: Dict[str, int] = {}
                for k, v in raw.items():
                    try:
                        out[str(k)] = int(v)
                    except (TypeError, ValueError):
                        continue
                return out
            except Exception:
                return {}
        return self._memory.hgetall(key)

    def _get_list(self, key: str) -> List[float]:
        if self._redis is not None:
            try:
                raw = self._redis.lrange(key, 0, MAX_LATENCY_SAMPLES - 1) or []
                out: List[float] = []
                for v in raw:
                    try:
                        out.append(float(v))
                    except (TypeError, ValueError):
                        continue
                return out
            except Exception:
                return []
        return self._memory.lrange(key)

    # -- recording API ------------------------------------------------------

    def record_message(self, direction: str = "incoming", client_id: Optional[int] = None,
                       amount: int = 1) -> None:
        """Record a message for throughput tracking."""
        try:
            minute = _minute_key()
            self._incr(f"{PREFIX}:throughput:{minute}", MINUTE_BUCKET_TTL, amount)
            self._incr(f"{PREFIX}:throughput:{direction}:{minute}", MINUTE_BUCKET_TTL, amount)
            if client_id is not None:
                self._incr(f"{PREFIX}:throughput:client:{client_id}:{minute}",
                           MINUTE_BUCKET_TTL, amount)
        except Exception as e:  # pragma: no cover
            logger.debug("record_message failed: %s", e)

    def record_llm_latency(self, latency_ms: float, provider: str = "default",
                           client_id: Optional[int] = None) -> None:
        """Record an LLM call latency sample (milliseconds)."""
        try:
            hour = _hour_key()
            self._push(f"{PREFIX}:llm_latency:{hour}", float(latency_ms), HOUR_BUCKET_TTL)
            self._hincr(f"{PREFIX}:llm_calls:{_day_key()}", provider, DAY_BUCKET_TTL)
            if client_id is not None:
                self._hincr(f"{PREFIX}:llm_calls_client:{_day_key()}", str(client_id),
                            DAY_BUCKET_TTL)
        except Exception as e:  # pragma: no cover
            logger.debug("record_llm_latency failed: %s", e)

    def record_tool_call(self, tool_name: str, success: bool,
                         duration_ms: Optional[float] = None) -> None:
        """Record a tool invocation outcome."""
        try:
            key = f"{PREFIX}:tools:{_day_key()}"
            self._hincr(key, f"{tool_name}:{'success' if success else 'error'}", DAY_BUCKET_TTL)
            self._hincr(key, f"__total__:{'success' if success else 'error'}", DAY_BUCKET_TTL)
            if duration_ms is not None:
                self._push(f"{PREFIX}:tool_latency:{_hour_key()}", float(duration_ms),
                           HOUR_BUCKET_TTL)
        except Exception as e:  # pragma: no cover
            logger.debug("record_tool_call failed: %s", e)

    def record_funnel_stage(self, stage: str, client_id: Optional[int] = None) -> None:
        """Record that a lead reached a funnel stage."""
        try:
            self._hincr(f"{PREFIX}:funnel:{_day_key()}", stage, DAY_BUCKET_TTL)
            if client_id is not None:
                self._hincr(f"{PREFIX}:funnel_client:{client_id}:{_day_key()}", stage,
                            DAY_BUCKET_TTL)
        except Exception as e:  # pragma: no cover
            logger.debug("record_funnel_stage failed: %s", e)

    def record_request(self, endpoint: str, status_code: int = 200,
                       duration_ms: Optional[float] = None) -> None:
        """Record an HTTP request and whether it errored."""
        try:
            day = _day_key()
            endpoint = endpoint or "unknown"
            self._hincr(f"{PREFIX}:requests:{day}", endpoint, DAY_BUCKET_TTL)
            if status_code >= 500:
                self._hincr(f"{PREFIX}:errors:{day}", endpoint, DAY_BUCKET_TTL)
            elif status_code >= 400:
                self._hincr(f"{PREFIX}:client_errors:{day}", endpoint, DAY_BUCKET_TTL)
            if duration_ms is not None:
                self._push(f"{PREFIX}:http_latency:{_hour_key()}", float(duration_ms),
                           HOUR_BUCKET_TTL)
        except Exception as e:  # pragma: no cover
            logger.debug("record_request failed: %s", e)

    def record_error(self, endpoint: str, error: str = "") -> None:
        """Record an unhandled error for an endpoint."""
        try:
            day = _day_key()
            self._hincr(f"{PREFIX}:errors:{day}", endpoint or "unknown", DAY_BUCKET_TTL)
            if error:
                self._hincr(f"{PREFIX}:error_types:{day}", error[:80], DAY_BUCKET_TTL)
        except Exception as e:  # pragma: no cover
            logger.debug("record_error failed: %s", e)

    def record(self, metric_name: str, value: float = 1.0,
               tags: Optional[Dict[str, Any]] = None) -> None:
        """Generic entry point used by logging_setup.log_metric()."""
        tags = tags or {}
        try:
            name = (metric_name or "unknown").strip()
            client_id = tags.get("client_id")
            client_id = int(client_id) if isinstance(client_id, (int, str)) and str(client_id).isdigit() else None

            if "llm" in name and "duration" in name or name.startswith("llm.latency"):
                self.record_llm_latency(value, str(tags.get("provider", "default")), client_id)
                return
            if name.startswith("tool."):
                tool = tags.get("tool") or name.split(".", 2)[1] if "." in name else "unknown"
                self.record_tool_call(str(tool), tags.get("status", "ok") != "error", value)
                return
            if name.startswith("message."):
                self.record_message(str(tags.get("direction", "incoming")), client_id)
                return
            if name.startswith("funnel."):
                self.record_funnel_stage(str(tags.get("stage", name.split(".", 1)[-1])), client_id)
                return
            # default: custom gauge/counter bucket
            self._hincr(f"{PREFIX}:custom:{_day_key()}", name, DAY_BUCKET_TTL, int(max(value, 0)) or 1)
        except Exception as e:  # pragma: no cover
            logger.debug("record(%s) failed: %s", metric_name, e)

    # -- reading API --------------------------------------------------------

    def get_throughput(self, minutes: int = 5) -> Dict[str, Any]:
        """Messages per minute over the last `minutes` minute-buckets."""
        now = datetime.now(timezone.utc)
        buckets: Dict[str, int] = {}
        for i in range(max(1, minutes)):
            dt = now - timedelta(minutes=i)
            mk = _minute_key(dt)
            buckets[mk] = self._get_int(f"{PREFIX}:throughput:{mk}")
        total = sum(buckets.values())
        return {
            "per_minute_current": buckets.get(_minute_key(now), 0),
            "per_minute_avg": round(total / max(1, len(buckets)), 2),
            "window_minutes": len(buckets),
            "window_total": total,
            "buckets": buckets,
        }

    def get_llm_latency(self, hours: int = 1) -> Dict[str, Any]:
        """p50/p95/p99 LLM latency over the last `hours` hour-buckets."""
        now = datetime.now(timezone.utc)
        samples: List[float] = []
        for i in range(max(1, hours)):
            samples.extend(self._get_list(f"{PREFIX}:llm_latency:{_hour_key(now - timedelta(hours=i))}"))
        return {
            "samples": len(samples),
            "p50": _percentile(samples, 50),
            "p95": _percentile(samples, 95),
            "p99": _percentile(samples, 99),
            "max": round(max(samples), 2) if samples else 0.0,
            "avg": round(sum(samples) / len(samples), 2) if samples else 0.0,
        }

    def get_tool_success_rate(self) -> Dict[str, Any]:
        """Success rate per tool and overall for today."""
        data = self._get_hash(f"{PREFIX}:tools:{_day_key()}")
        per_tool: Dict[str, Dict[str, Any]] = {}
        for field, count in data.items():
            if ":" not in field:
                continue
            tool, outcome = field.rsplit(":", 1)
            entry = per_tool.setdefault(tool, {"success": 0, "error": 0})
            if outcome in entry:
                entry[outcome] += count
        for tool, entry in per_tool.items():
            total = entry["success"] + entry["error"]
            entry["total"] = total
            entry["success_rate"] = round(entry["success"] / total * 100, 2) if total else 0.0
        overall = per_tool.get("__total__", {"success": 0, "error": 0, "total": 0, "success_rate": 0.0})
        return {
            "overall_success_rate": overall.get("success_rate", 0.0),
            "total_calls": overall.get("total", 0),
            "per_tool": {k: v for k, v in per_tool.items() if k != "__total__"},
        }

    def get_funnel_drop_off(self) -> Dict[str, Any]:
        """Drop-off rate between consecutive funnel stages for today."""
        counts = self._get_hash(f"{PREFIX}:funnel:{_day_key()}")
        stages = {stage: int(counts.get(stage, 0)) for stage in FUNNEL_STAGES}
        for extra_stage, value in counts.items():
            stages.setdefault(extra_stage, int(value))
        drop_off: Dict[str, float] = {}
        for i in range(len(FUNNEL_STAGES) - 1):
            current, nxt = FUNNEL_STAGES[i], FUNNEL_STAGES[i + 1]
            base = stages.get(current, 0)
            follow = stages.get(nxt, 0)
            drop_off[f"{current}->{nxt}"] = (
                round(max(0.0, (base - follow) / base * 100), 2) if base else 0.0
            )
        entry = stages.get(FUNNEL_STAGES[0], 0)
        completed = stages.get(FUNNEL_STAGES[-1], 0)
        return {
            "stage_counts": stages,
            "drop_off_rates": drop_off,
            "overall_drop_off": round(max(0.0, (entry - completed) / entry * 100), 2) if entry else 0.0,
        }

    def get_error_rates(self, top: int = 10) -> Dict[str, Any]:
        """Error rate per endpoint for today."""
        day = _day_key()
        requests = self._get_hash(f"{PREFIX}:requests:{day}")
        errors = self._get_hash(f"{PREFIX}:errors:{day}")
        client_errors = self._get_hash(f"{PREFIX}:client_errors:{day}")
        per_endpoint: Dict[str, Dict[str, Any]] = {}
        for endpoint, total in requests.items():
            err = int(errors.get(endpoint, 0))
            per_endpoint[endpoint] = {
                "requests": int(total),
                "server_errors": err,
                "client_errors": int(client_errors.get(endpoint, 0)),
                "error_rate": round(err / int(total) * 100, 2) if int(total) else 0.0,
            }
        # endpoints that only produced errors (never counted as requests)
        for endpoint, err in errors.items():
            per_endpoint.setdefault(endpoint, {
                "requests": 0, "server_errors": int(err), "client_errors": 0, "error_rate": 100.0,
            })
        total_requests = sum(v["requests"] for v in per_endpoint.values())
        total_errors = sum(v["server_errors"] for v in per_endpoint.values())
        worst = sorted(per_endpoint.items(), key=lambda kv: kv[1]["error_rate"], reverse=True)[:top]
        return {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "overall_error_rate": round(total_errors / total_requests * 100, 2) if total_requests else 0.0,
            "by_endpoint": dict(worst),
        }

    def get_summary(self) -> Dict[str, Any]:
        """Full metrics snapshot for the admin dashboard."""
        try:
            return {
                "backend": self.backend,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "message_throughput": self.get_throughput(minutes=5),
                "llm_latency_ms": self.get_llm_latency(hours=1),
                "tool_calls": self.get_tool_success_rate(),
                "funnel": self.get_funnel_drop_off(),
                "errors": self.get_error_rates(),
            }
        except Exception as e:
            logger.error("get_summary failed: %s", e)
            return {
                "backend": self.backend,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }

    def reset_memory(self) -> None:
        """Clear the in-memory fallback store (used by tests)."""
        self._memory.reset()


class Timer:
    """Small helper to time a block and report it to the collector.

    Usage:
        with Timer() as t:
            ...
        metrics_collector.record_llm_latency(t.duration_ms)
    """

    def __init__(self) -> None:
        self.started_at = 0.0
        self.duration_ms = 0.0

    def __enter__(self) -> "Timer":
        self.started_at = time.time()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.duration_ms = round((time.time() - self.started_at) * 1000, 2)


# Global collector instance
metrics_collector = MetricsCollector()
