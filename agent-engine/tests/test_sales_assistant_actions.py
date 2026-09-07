"""Tests for the Sales-Assistant action protocol (chat_assistant.py)."""
import asyncio

from chat_assistant import _validate_media_url, _execute_create_order


def test_validate_media_url_rejects_non_https():
    assert _validate_media_url("http://cdn.example.com/x.jpg", {}) is False
    assert _validate_media_url("", {}) is False
    assert _validate_media_url(None, {}) is False


def test_validate_media_url_rejects_unlisted_url():
    # https but NOT provided by the business -> blocked (anti-SSRF / anti-injection)
    assert _validate_media_url("https://evil.example.com/pwn.jpg", {}) is False


def test_validate_media_url_accepts_profile_url():
    profile = {"welcome_image": "https://cdn.myshop.com/menu.jpg"}
    assert _validate_media_url("https://cdn.myshop.com/menu.jpg", profile) is True


def test_create_order_rejects_bad_amount():
    # invalid amount short-circuits before any DB access
    out = asyncio.run(_execute_create_order(
        {"type": "create_order", "amount": "abc"}, 1, "919999999999", {}))
    assert out is None
    out = asyncio.run(_execute_create_order(
        {"type": "create_order", "amount": 0}, 1, "919999999999", {}))
    assert out is None
    out = asyncio.run(_execute_create_order(
        {"type": "create_order"}, 1, "919999999999", {}))
    assert out is None
