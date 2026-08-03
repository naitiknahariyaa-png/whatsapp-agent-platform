"""
Structured logging + Sentry integration for the WhatsApp Agent Platform.
Provides:
  - JSON-formatted structured logs (stdlib logging + python-json-logger)
  - Sentry error tracking (auto-init from settings)
  - Helper decorators and context managers for tracing requests
"""
import os
import sys
import logging
from logging.config import dictConfig
from typing import Optional, Dict, Any
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


# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

def _build_formatter():
    if HAS_JSON_LOGGER:
        return {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "rename_fields": {"asctime": "timestamp", "levelname": "level", "name": "logger"},
        }
    return LOG_FORMAT


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure structured logging for the whole app."""
    formatter = _build_formatter() if json_output else LOG_FORMAT

    handlers = {
        "default": {
            "level": level,
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json" if json_output else "default",
        },
        "access": {
            "level": level,
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json" if json_output else "default",
        },
    }
    formatters = {"default": {"format": LOG_FORMAT}}
    if json_output:
        formatters["json"] = formatter

    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": handlers,
        "loggers": {
            "": {"handlers": ["default"], "level": level},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "wap": {"handlers": ["default"], "level": level, "propagate": False},
        },
    })


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

@contextmanager
def request_scope(**kwargs):
    """Bind request-scoped data (request_id, phone_number, client_id, ...) to logs."""
    ctx = request_context.get()
    new_ctx = {**ctx, **kwargs}
    token = request_context.set(new_ctx)
    try:
        yield new_ctx
    finally:
        request_context.reset(token)


class ContextFilter(logging.Filter):
    """Inject request-context fields into every log record."""
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_context.get()
        record.request_id = ctx.get("request_id", "-")
        record.phone_number = ctx.get("phone_number", "-")
        record.client_id = ctx.get("client_id", "-")
        return True


def install_context_filter() -> None:
    """Attach ContextFilter to the root logger."""
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, ContextFilter) for f in handler.filters):
            handler.addFilter(ContextFilter())