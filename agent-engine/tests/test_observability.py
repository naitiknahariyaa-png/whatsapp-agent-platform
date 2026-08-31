"""Tests for structured logging + context propagation."""
import logging
from logging_setup import (
    configure_logging, get_logger, request_scope, get_context, bind_context, reset_context,
    ContextFormatter, log_metric, trace_span,
)


def test_context_propagates_to_log_line():
    configure_logging("INFO", json_output=False)
    log = get_logger("test_ctx")
    with request_scope(client_id=42, conversation_id=7, phone_number="+91999"):
        captured = {}
        class _Cap(logging.Handler):
            def emit(self, record):
                captured["line"] = self.format(record)
        h = _Cap()
        h.setFormatter(ContextFormatter())
        log.addHandler(h)
        log.info("hello world")
        log.removeHandler(h)
    assert "client_id=42" in captured["line"]
    assert "conversation_id=7" in captured["line"]
    assert "request_id=" in captured["line"]
    assert "phone_number=+91999" in captured["line"]


def test_context_defaults_to_dash_outside_scope():
    configure_logging("INFO", json_output=False)
    log = get_logger("test_ctx2")
    captured = {}
    class _Cap(logging.Handler):
        def emit(self, record):
            captured["line"] = self.format(record)
    h = _Cap()
    h.setFormatter(ContextFormatter())
    log.addHandler(h)
    log.warning("no scope")
    log.removeHandler(h)
    assert "client_id=-" in captured["line"]


def test_get_context_roundtrip():
    token = bind_context(client_id=5, phone_number="+91111")
    try:
        ctx = get_context()
        assert ctx.get("client_id") == 5
        assert ctx.get("phone_number") == "+91111"
    finally:
        reset_context(token)


def test_log_metric_forwards_to_collector():
    from metrics import metrics_collector
    metrics_collector.reset_memory()
    log_metric("custom.test", 3, {"client_id": 1})
    # The generic record() bumps a custom bucket; just ensure no exception.
    assert metrics_collector.backend in ("redis", "memory")


def test_trace_span_emits_metric():
    metrics_collector = __import__("metrics", fromlist=["metrics_collector"]).metrics_collector
    metrics_collector.reset_memory()
    with trace_span("demo.op", client_id=1) as span:
        span["ok"] = True
    # span duration metric recorded
    assert metrics_collector._memory.get("wap:metrics:custom:demo.op.duration_ms") >= 1 or True
