"""
Observability Tracing
=====================

Full trace per conversation following a message through:
Manager → Specialist → Tool → Response

Features:
- Single trace ID per conversation turn
- Structured spans for each step
- Automatic instrumentation of orchestrator, tools, LLM calls
- Export to multiple backends (stdout, file, OTLP)
- Correlation with logs, metrics, and approval gates
"""
import os
import uuid
import time
import logging
import asyncio
import contextvars
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from contextlib import asynccontextmanager
from functools import wraps

logger = logging.getLogger("tracing")


class SpanKind(Enum):
    """Type of span."""
    SERVER = "server"           # Incoming request
    CLIENT = "client"           # Outbound call
    INTERNAL = "internal"       # Internal processing
    LLM = "llm"                 # LLM call
    TOOL = "tool"               # Tool execution
    AGENT = "agent"             # Agent step
    DATABASE = "database"       # DB operation
    CACHE = "cache"             # Cache operation
    APPROVAL = "approval"       # Approval gate
    GUARDRAIL = "guardrail"     # Guardrail check


class SpanStatus(Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class Span:
    """A single trace span."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    name: str
    kind: SpanKind
    status: SpanStatus = SpanStatus.OK
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def finish(self, status: SpanStatus = SpanStatus.OK, error: str = None):
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        if error:
            self.error = error
            self.attributes["error"] = error

    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def set_attribute(self, key: str, value: Any):
        self.attributes[key] = value

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        return d


# ─── Context Management ────────────────────────────────────────────

_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("trace_id", default=None)
_span_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("span_id", default=None)
_current_span_var: contextvars.ContextVar[Optional[Span]] = contextvars.ContextVar("current_span", default=None)


def get_trace_id() -> Optional[str]:
    return _trace_id_var.get()


def get_span_id() -> Optional[str]:
    return _span_id_var.get()


def get_current_span() -> Optional[Span]:
    return _current_span_var.get()


def set_trace_context(trace_id: str, span_id: str, span: Span):
    _trace_id_var.set(trace_id)
    _span_id_var.set(span_id)
    _current_span_var.set(span)


def clear_trace_context():
    _trace_id_var.set(None)
    _span_id_var.set(None)
    _current_span_var.set(None)


# ─── Tracer ────────────────────────────────────────────────────────

class Tracer:
    """Distributed tracer for conversation turns."""

    def __init__(self, service_name: str = "whatsapp-agent"):
        self.service_name = service_name
        self._exporters: List[Callable[[Span], None]] = []
        self._sampler = lambda: True  # Sample all by default

    def add_exporter(self, exporter: Callable[[Span], None]):
        self._exporters.append(exporter)

    def set_sampler(self, sampler: Callable[[], bool]):
        self._sampler = sampler

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        parent_span: Optional[Span] = None,
        attributes: Dict[str, Any] = None,
    ) -> Span:
        """Start a new span."""
        trace_id = parent_span.trace_id if parent_span else str(uuid.uuid4())
        span_id = str(uuid.uuid4())[:16]
        parent_span_id = parent_span.span_id if parent_span else None

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=name,
            kind=kind,
            attributes=attributes or {},
        )

        # Set context
        set_trace_context(trace_id, span_id, span)

        # Log start
        logger.debug("TRACE %s | SPAN %s | START %s (%s)", trace_id[:8], span_id[:8], name, kind.value)

        return span

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK, error: str = None):
        """End a span and export."""
        span.finish(status, error)

        # Export
        for exporter in self._exporters:
            try:
                exporter(span)
            except Exception as e:
                logger.warning("Span exporter failed: %s", e)

        # Clear context if this was the current span
        if get_current_span() is span:
            clear_trace_context()

        logger.debug("TRACE %s | SPAN %s | END %s | %.1fms | %s",
                     span.trace_id[:8], span.span_id[:8], span.name, span.duration_ms, status.value)

    @asynccontextmanager
    async def span(self, name: str, kind: SpanKind = SpanKind.INTERNAL, **attrs):
        """Async context manager for spans."""
        span = self.start_span(name, kind, attributes=attrs)
        try:
            yield span
        except Exception as e:
            self.end_span(span, SpanStatus.ERROR, str(e))
            raise
        else:
            self.end_span(span, SpanStatus.OK)

    def trace(self, name: str, kind: SpanKind = SpanKind.INTERNAL, **attrs):
        """Decorator for tracing functions."""
        def decorator(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                async with self.span(name, kind, **attrs) as span:
                    return await func(*args, **kwargs)

            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                with self.span(name, kind, **attrs) as span:
                    return func(*args, **kwargs)

            import asyncio
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper
        return decorator


# ─── Exporters ─────────────────────────────────────────────────────

def console_exporter(span: Span):
    """Export span to console (JSON)."""
    print(json.dumps(span.to_dict(), default=str))


def file_exporter(span: Span):
    """Export span to file (rotating)."""
    log_dir = Path("logs/traces")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"traces_{datetime.utcnow().strftime('%Y%m%d')}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(span.to_dict(), default=str) + "\n")


def otlp_exporter(span: Span):
    """Export to OTLP (OpenTelemetry) - placeholder."""
    # In production, use opentelemetry-sdk
    pass


# ─── Global Tracer ────────────────────────────────────────────────

_tracer = Tracer("whatsapp-agent")
_tracer.add_exporter(console_exporter)
_tracer.add_exporter(file_exporter)


def get_tracer() -> Tracer:
    return _tracer


# ─── Convenience Functions ─────────────────────────────────────────

def start_trace(name: str, kind: SpanKind = SpanKind.SERVER, **attrs) -> Span:
    """Start a new trace (root span)."""
    return _tracer.start_span(name, kind, attributes=attrs)


def trace_llm_call(model: str, task_type: str, **attrs) -> Span:
    """Trace an LLM call."""
    return _tracer.start_span(
        f"llm.{task_type}",
        SpanKind.LLM,
        attributes={"model": model, "task_type": task_type, **attrs},
    )


def trace_tool_call(tool_name: str, **attrs) -> Span:
    """Trace a tool call."""
    return _tracer.start_span(
        f"tool.{tool_name}",
        SpanKind.TOOL,
        attributes={"tool": tool_name, **attrs},
    )


def trace_agent_step(agent_name: str, step: str, **attrs) -> Span:
    """Trace an agent step."""
    return _tracer.start_span(
        f"agent.{agent_name}.{step}",
        SpanKind.AGENT,
        attributes={"agent": agent_name, "step": step, **attrs},
    )


def trace_db_query(query_type: str, table: str, **attrs) -> Span:
    """Trace a database query."""
    return _tracer.start_span(
        f"db.{query_type}",
        SpanKind.DATABASE,
        attributes={"table": table, "query_type": query_type, **attrs},
    )


def trace_cache_operation(op: str, **attrs) -> Span:
    """Trace a cache operation."""
    return _tracer.start_span(
        f"cache.{op}",
        SpanKind.CACHE,
        attributes={"operation": op, **attrs},
    )


# ─── Conversation Trace Context ────────────────────────────────────

@dataclass
class ConversationTrace:
    """Complete trace for a single conversation turn."""
    trace_id: str
    client_id: int
    phone_number: str
    language: str
    vertical: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    spans: List[Span] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_span(self, span: Span):
        self.spans.append(span)

    def finish(self):
        self.end_time = time.time()
        total_ms = (self.end_time - self.start_time) * 1000
        logger.info(
            "CONV_TRACE %s | client=%d phone=%s lang=%s vertical=%s | %d spans | %.1fms",
            self.trace_id[:8], self.client_id, self.phone_number[-4:],
            self.language, self.vertical, len(self.spans), total_ms
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "client_id": self.client_id,
            "phone_number": self.phone_number,
            "language": self.language,
            "vertical": self.vertical,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": (self.end_time - self.start_time) * 1000 if self.end_time else 0,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
            "metadata": self.metadata,
        }


class ConversationTracer:
    """Manages traces for a conversation turn."""

    def __init__(self):
        self._current_trace: Optional[ConversationTrace] = None

    @asynccontextmanager
    async def trace_conversation(
        self,
        client_id: int,
        phone_number: str,
        language: str,
        vertical: str,
        metadata: Dict[str, Any] = None,
    ):
        """Context manager for tracing a full conversation turn."""
        trace = ConversationTrace(
            trace_id=str(uuid.uuid4()),
            client_id=client_id,
            phone_number=phone_number,
            language=language,
            vertical=vertical,
            metadata=metadata or {},
        )
        self._current_trace = trace

        # Set as root span context
        root_span = _tracer.start_span(
            "conversation.turn",
            SpanKind.SERVER,
            attributes={
                "client_id": client_id,
                "phone_number": phone_number[-4:],
                "language": language,
                "vertical": vertical,
            },
        )

        try:
            yield trace
        except Exception as e:
            logger.exception("Conversation trace error: %s", e)
            raise
        finally:
            trace.finish()
            # Export full trace
            self._export_trace(trace)
            self._current_trace = None

    def _export_trace(self, trace: ConversationTrace):
        """Export full conversation trace."""
        trace_data = trace.to_dict()
        # Log full trace
        logger.info("FULL_TRACE %s", json.dumps(trace_data, default=str))
        # Could also send to external system

    def get_current_trace(self) -> Optional[ConversationTrace]:
        return self._current_trace


# ─── Global Instances ──────────────────────────────────────────────

conversation_tracer = ConversationTracer()


# ─── Decorators for Common Operations ──────────────────────────────

def traced_llm_call(task_type: str, model: str = ""):
    """Decorator for tracing LLM calls."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            span = trace_llm_call(model, task_type)
            try:
                result = await func(*args, **kwargs)
                span.set_attribute("success", True)
                return result
            except Exception as e:
                span.set_attribute("success", False)
                span.set_attribute("error", str(e))
                raise
            finally:
                _tracer.end_span(span)
        return wrapper
    return decorator


def traced_tool_call(tool_name: str):
    """Decorator for tracing tool calls."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            span = trace_tool_call(tool_name)
            try:
                result = await func(*args, **kwargs)
                span.set_attribute("success", True)
                return result
            except Exception as e:
                span.set_attribute("success", False)
                span.set_attribute("error", str(e))
                raise
            finally:
                _tracer.end_span(span)
        return wrapper
    return decorator


# ─── Integration with Existing Components ──────────────────────────

def trace_orchestrator_process(turn_func: callable):
    """Decorator to trace the full orchestrator process."""
    @wraps(turn_func)
    async def wrapper(*args, **kwargs):
        # Extract context from args/kwargs
        client_id = kwargs.get("client_id", 1)
        phone_number = kwargs.get("phone_number", "") or args[0] if args else ""
        language = kwargs.get("language", "en")
        vertical = kwargs.get("vertical", "general")

        async with conversation_tracer.trace_conversation(
            client_id=client_id,
            phone_number=phone_number,
            language=language,
            vertical=vertical,
            metadata={"function": turn_func.__name__},
        ) as trace:
            return await turn_func(*args, **kwargs)
    return wrapper