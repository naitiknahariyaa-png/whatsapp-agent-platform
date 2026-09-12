"""CLI functional registry tests: list, run sync/async, params, errors."""
import pytest

from cli_registry import (list_functional, run_functional, register,
                          REGISTRY, _report_build)


def test_list_and_curated_set():
    rows = list_functional()
    names = {r["name"] for r in rows}
    assert {"accounts.list", "accounts.setup", "accounts.run",
            "report.load", "report.build", "creative.plan",
            "prompt.build", "prompt.build-client",
            "broadcast.copy"} <= names
    for r in rows:
        assert r["help"] and r["module"] and r["attr"]


def test_run_sync_with_kwargs():
    out = run_functional("prompt.build", {"profile": {
        "business_name": "My Salon", "brand_voice": "casual",
        "menu": [{"name": "Haircut", "price": 299}]}})
    assert "My Salon" in out and "Haircut" in out
    assert "ANTI-HALLUCINATION" in out


def test_run_async_functional():
    import asyncio
    from db import init_db
    asyncio.run(init_db())
    run_functional("accounts.setup",
                   {"path": "../samples/profiles.sample.json"})
    res = run_functional("accounts.list")
    assert isinstance(res, list) and len(res) >= 3
    assert {"business_name", "client_id"} <= set(res[0].keys())


def test_unknown_and_custom_registration():
    with pytest.raises(KeyError):
        run_functional("nope.nope")
    def _echo(x=1):
        return x * 2
    register("test.echo", "echo helper", __name__, "_echo_helper")
    REGISTRY["test.echo"]["module"] = __name__
    globals()["_echo_helper"] = _echo
    assert run_functional("test.echo", {"x": 5}) == 10
    del REGISTRY["test.echo"]
