"""
Structured logging + Sentry integration for the WhatsApp Agent Platform.
Provides:
  - JSON-formatted structured logs (stdlib logging + python-json-logger)
  - Sentry error tracking (auto-init from settings)
  - Request-scoped context (request_id, client_id, conversation_id, phone_number)
    injected into EVERY log line
  - log_metric() for structured metric emission
  - trace_span() context manager for latency tracing
"""
import os
import sys
import time
import uuid
import logging
from logging.config import dictConfig
from typing import Optional, Dict, Any, Iterator
from contextvars import ContextVar
from contextlib import contextmanager

try:
    from pythonjsonlogger import jsonlogger
    HAS_JSON_LOGGER = True
except ImportError:
    HAS_JSON_LOGGER = False

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    HAS_SENTRY = True
except ImportError:
    HAS_SENTRY = False


# Context variable to track request-scoped data (request_id, phone, client_id)
request_context: ContextVar[Dict[str, Any]] = ContextVar("request_context", default={})

# Fields that must appear on EVERY log record (task: observability)
CONTEXT_FIELDS = ("request_id", "client_id", "conversation_id", "phone_number")


# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

BASE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
CONTEXT_SUFFIX = (
    " | client_id=%(client_id)s conversation_id=%(conversation_id)s "
    "request_id=%(request_id)s phone_number=%(phone_number)s"
)
LOG_FORMAT = BASE_FORMAT + CONTEXT_SUFFIX

JSON_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s %(message)s "
    "%(client_id)s %(conversation_id)s %(request_id)s %(phone_number)s"
)


def _ensure_context_attrs(record: logging.LogRecord) -> None:
    """Guarantee context attributes exist on a record (never raise on format)."""
    ctx = {}
    try:
        ctx = request_context.get() or {}
    except LookupError:  # pragma: no cover - contextvar always has a default
        ctx = {}
    for field in CONTEXT_FIELDS:
        if not hasattr(record, field) or getattr(record, field, None) in (None, ""):
            setattr(record, field, ctx.get(field, "-"))


class ContextFormatter(logging.Formatter):
    """Text formatter that always renders the request-scoped context fields."""

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None):
        super().__init__(fmt or LOG_FORMAT, datefmt)

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        _ensure_context_attrs(record)
        return super().format(record)


def _build_json_formatter() -> Dict[str, Any]:
    """Return a dictConfig formatter spec for JSON logs."""
    if HAS_JSON_LOGGER:
        return {
            "()": "logging_setup.ContextJsonFormatter",
            "format": JSON_FORMAT,
            "rename_fields": {"asctime": "timestamp", "levelname": "level", "name": "logger"},
        }
    return {"()": "logging_setup.ContextFormatter", "format": LOG_FORMAT}


if HAS_JSON_LOGGER:

    class ContextJsonFormatter(jsonlogger.JsonFormatter):  # type: ignore[misc]
        """JSON formatter that always includes the request-scoped context fields."""

        def add_fields(self, log_record, record, message_dict):  # noqa: ANN001
            _ensure_context_attrs(record)
            super().add_fields(log_record, record, message_dict)
            for field in CONTEXT_FIELDS:
                log_record.setdefault(field, getattr(record, field, "-"))

else:  # pragma: no cover - only when python-json-logger is missing

    class ContextJsonFormatter(ContextFormatter):  # type: ignore[no-redef]
        """Fallback: plain text formatter when python-json-logger is unavailable."""


def _build_formatter():
    """Backwards-compatible helper (kept for callers/tests that used it)."""
    return _build_json_formatter() if HAS_JSON_LOGGER else LOG_FORMAT


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structured logging for the whole app.

    Every handler gets the ContextFilter attached so that client_id,
    conversation_id, request_id and phone_number are present on all log lines.
    """
    formatter_name = "json" if json_output else "default"

    handlers = {
        "default": {
            "level": level,
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": formatter_name,
            "filters": ["context"],
        },
        "access": {
            "level": level,
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": formatter_name,
            "filters": ["context"],
        },
    }
    formatters: Dict[str, Any] = {
        "default": {"()": "logging_setup.ContextFormatter", "format": LOG_FORMAT},
    }
    if json_output:
        formatters["json"] = _build_json_formatter()

    try:
        dictConfig({
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"context": {"()": "logging_setup.ContextFilter"}},
            "formatters": formatters,
            "handlers": handlers,
            "loggers": {
                "": {"handlers": ["default"], "level": level},
                "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
                "wap": {"handlers": ["default"], "level": level, "propagate": False},
            },
        })
    except Exception as e:  # pragma: no cover - never let logging setup kill the app
        logging.basicConfig(level=level, format=BASE_FORMAT, stream=sys.stdout)
        logging.getLogger("wap.logging").warning("Falling back to basicConfig: %s", e)
    install_context_filter()


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the 'wap' namespace."""
    return logging.getLogger(f"wap.{name}")


# ---------------------------------------------------------------------------
# Sentry setup
# ---------------------------------------------------------------------------

def init_sentry(dsn: Optional[str] = None, environment: str = "development",
                traces_sample_rate: float = 0.1) -> bool:
    """Initialize Sentry if DSN is provided. Returns True on success."""
    dsn = dsn or os.getenv("SENTRY_DSN", "")
    if not dsn or not HAS_SENTRY:
        if not HAS_SENTRY:
            get_logger("sentry").warning("sentry-sdk not installed, skipping Sentry init")
        else:
            get_logger("sentry").info("No SENTRY_DSN configured, skipping Sentry init")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=traces_sample_rate,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                RedisIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            send_default_pii=False,
        )
        get_logger("sentry").info(f"Sentry initialized (env={environment}, rate={traces_sample_rate})")
        return True
    except Exception as e:
        get_logger("sentry").error(f"Failed to init Sentry: {e}")
        return False


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def new_request_id() -> str:
    """Generate a short unique request id."""
    return uuid.uuid4().hex[:16]


def get_context() -> Dict[str, Any]:
    """Return a copy of the current request-scoped log context."""
    try:
        return dict(request_context.get() or {})
    except LookupError:  # pragma: no cover
        return {}


def bind_context(**kwargs) -> Any:
    """Merge values into the current context. Returns a reset token."""
    ctx = get_context()
    clean = {k: v for k, v in kwargs.items() if v is not None}
    return request_context.set({**ctx, **clean})


def reset_context(token: Any) -> None:
    """Reset the context to a previous token (best-effort)."""
    try:
        request_context.reset(token)
    except Exception:  # pragma: no cover - token from another context
        pass


@contextmanager
def request_scope(**kwargs) -> Iterator[Dict[str, Any]]:
    """Bind request-scoped data (request_id, phone_number, client_id, ...) to logs."""
    ctx = get_context()
    new_ctx = {**ctx, **{k: v for k, v in kwargs.items() if v is not None}}
    new_ctx.setdefault("request_id", new_request_id())
    token = request_context.set(new_ctx)
    try:
        yield new_ctx
    finally:
        reset_context(token)


class ContextFilter(logging.Filter):
    """Inject request-context fields into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_context()
        for field in CONTEXT_FIELDS:
            current = getattr(record, field, None)
            if current in (None, ""):
                setattr(record, field, ctx.get(field, "-"))
        return True


def install_context_filter() -> None:
    """Attach ContextFilter to the root logger and every configured handler."""
    loggers = [logging.getLogger()] + [
        logging.getLogger(name) for name in ("wap", "uvicorn.access", "uvicorn.error")
    ]
    for lg in loggers:
        for handler in list(lg.handlers):
            if not any(isinstance(f, ContextFilter) for f in handler.filters):
                handler.addFilter(ContextFilter())


# ---------------------------------------------------------------------------
# Metrics + tracing helpers
# ---------------------------------------------------------------------------

_metric_logger = logging.getLogger("wap.metrics")


def log_metric(metric_name: str, value: float = 1.0, tags: Optional[Dict[str, Any]] = None) -> None:
    """Emit a structured metric line and forward it to the MetricsCollector.

    Never raises — metrics must not break request handling.
    """
    tags = tags or {}
    ctx = get_context()
    payload = {
        "metric": metric_name,
        "value": value,
        "tags": tags,
        "client_id": tags.get("client_id", ctx.get("client_id", "-")),
    }
    try:
        _metric_logger.info("metric %s=%s %s", metric_name, value, tags, extra=payload)
    except Exception:  # pragma: no cover
        pass
    try:
        from metrics import metrics_collector  # local import avoids circular import

        metrics_collector.record(metric_name, value, tags)
    except Exception:
        # metrics backend unavailable — the structured log line above is the fallback
        pass


@contextmanager
def trace_span(name: str, **kwargs) -> Iterator[Dict[str, Any]]:
    """Time a block of work, log start/end and emit a latency metric.

    Usage:
        with trace_span("llm.generate", client_id=1) as span:
            span["tokens"] = 120
    """
    span: Dict[str, Any] = {"name": name, "started_at": time.time(), **kwargs}
    logger = logging.getLogger("wap.trace")
    sentry_span_cm = None
    sentry_span = None
    if HAS_SENTRY:
        try:
            sentry_span_cm = sentry_sdk.start_span(op="task", description=name)
            sentry_span = sentry_span_cm.__enter__()
        except Exception:  # pragma: no cover
            sentry_span_cm = None
    ctx_token = bind_context(**{k: v for k, v in kwargs.items() if k in CONTEXT_FIELDS})
    logger.debug("span.start %s %s", name, kwargs)
    error: Optional[BaseException] = None
    try:
        yield span
    except BaseException as e:  # noqa: BLE001 - re-raised below
        error = e
        raise
    finally:
        duration_ms = round((time.time() - span["started_at"]) * 1000, 2)
        span["duration_ms"] = duration_ms
        span["status"] = "error" if error else "ok"
        try:
            if error:
                logger.error("span.end %s duration_ms=%s error=%s", name, duration_ms, error)
            else:
                logger.info("span.end %s duration_ms=%s", name, duration_ms)
            log_metric(
                f"span.{name}.duration_ms",
                duration_ms,
                {**{k: v for k, v in kwargs.items() if isinstance(v, (str, int, float))},
                 "status": span["status"]},
            )
        except Exception:  # pragma: no cover
            pass
        if sentry_span_cm is not None:
            try:
                if sentry_span is not None and hasattr(sentry_span, "set_data"):
                    sentry_span.set_data("duration_ms", duration_ms)
                sentry_span_cm.__exit__(None, None, None)
            except Exception:  # pragma: no cover
                pass
        reset_context(ctx_token)
