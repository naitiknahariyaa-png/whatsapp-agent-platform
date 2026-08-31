"""Tests for webhook signature verification + input sanitisation."""
import hmac
import hashlib
from security import verify_bridge_webhook, verify_bridge_webhook_with_timestamp, sanitize_text, sanitize_phone
from config import settings


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_bridge_webhook_valid(monkeypatch):
    monkeypatch.setattr(settings, "wa_bridge_secret", "supersecret")
    body = b'{"event":"message"}'
    sig = _sign(body, "supersecret")
    assert verify_bridge_webhook(body, sig) is True


def test_verify_bridge_webhook_tampered(monkeypatch):
    monkeypatch.setattr(settings, "wa_bridge_secret", "supersecret")
    body = b'{"event":"message"}'
    bad = _sign(b'{"event":"hacked"}', "supersecret")
    assert verify_bridge_webhook(body, bad) is False


def test_verify_bridge_webhook_missing_signature(monkeypatch):
    monkeypatch.setattr(settings, "wa_bridge_secret", "supersecret")
    assert verify_bridge_webhook(b"x", None) is False


def test_verify_bridge_webhook_timestamp_replay(monkeypatch):
    monkeypatch.setattr(settings, "wa_bridge_secret", "supersecret")
    body = b"payload"
    sig = _sign(body, "supersecret")
    old_ts = 1  # far in the past
    assert verify_bridge_webhook_with_timestamp(body, sig, old_ts) is False
    import time
    assert verify_bridge_webhook_with_timestamp(body, sig, int(time.time())) is True


def test_sanitize_text_truncates():
    out = sanitize_text("a" * 5000, max_len=100)
    assert len(out) == 100


def test_sanitize_phone():
    assert sanitize_phone("+91 99999 99999") == "+919999999999"
    assert sanitize_phone("not a phone") == ""
