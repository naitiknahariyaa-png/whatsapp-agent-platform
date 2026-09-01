"""Tests for the ops CLI (cli.py + cli_commands.py) — HTTP mocked, offline-safe."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cli_commands as cc  # noqa: E402


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_start_server_already_running():
    with patch.object(cc.httpx, "get", return_value=_Resp(200, {"status": "ok"})):
        ok, msg = cc.cmd_start_server()
    assert ok and "already running" in msg


def test_generate_report_calls_correct_endpoint():
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"week_start": "2026-08-24"})) as m:
        ok, data = cc.cmd_generate_report(client_id=7, token="T")
    assert ok and data["week_start"] == "2026-08-24"
    args, kwargs = m.call_args
    assert args[0] == "POST" and args[1].endswith("/weekly_report/generate")
    assert kwargs["params"] == {"client_id": 7}
    assert kwargs["headers"]["Authorization"] == "Bearer T"


def test_run_reengage_and_stop():
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"status": "ok"})) as m:
        ok, _ = cc.cmd_run_reengage(token="T")
        assert ok
        assert m.call_args[0][1].endswith("/reengagement/run")
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"status": "ok"})) as m:
        ok, _ = cc.cmd_stop_reengage(12, "opted_out", token="T")
        assert ok
        assert m.call_args[0][1].endswith("/reengagement/stop")
        assert m.call_args[1]["json"] == {"lead_id": 12, "reason": "opted_out"}


def test_list_alerts_and_trigger():
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"alerts": [], "count": 0})) as m:
        ok, data = cc.cmd_list_alerts(token="T")
        assert ok and data["count"] == 0
        assert m.call_args[0][0] == "GET" and m.call_args[0][1].endswith("/alerts")
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"alerts": [], "count": 0})) as m:
        ok, _ = cc.cmd_trigger_alerts(token="T")
        assert ok and m.call_args[0][0] == "POST"


def test_approval_request_body():
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"id": "r1"})) as m:
        ok, data = cc.cmd_approval_request("refund", 5000, {"x": 1}, "conv-1", token="T")
    assert ok and data["id"] == "r1"
    body = m.call_args[1]["json"]
    assert body == {"action_type": "refund", "payload": {"x": 1},
                    "amount": 5000, "conversation_id": "conv-1"}


def test_approval_decision_approve_and_reject():
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"status": "approved"})) as m:
        ok, _ = cc.cmd_approval_decision("r1", True, "ok", token="T")
        assert ok
        assert m.call_args[0][1].endswith("/api/approvals/r1/decide")
        assert m.call_args[1]["json"]["decision"] == "approved"
    with patch.object(cc.httpx, "request", return_value=_Resp(200, {"status": "rejected"})) as m:
        ok, _ = cc.cmd_approval_decision("r1", False, "no", token="T")
        assert ok and m.call_args[1]["json"]["decision"] == "rejected"


def test_call_unreachable_server_message():
    class _ConnErr(Exception):
        pass
    with patch.object(cc.httpx, "request", side_effect=cc.httpx.ConnectError("boom")):
        ok, msg = cc.cmd_list_alerts(token="T")
    assert not ok and "start-server" in msg


def test_load_payload_file(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"reason": "damaged"}), encoding="utf-8")
    assert cc.load_payload_file(str(f)) == {"reason": "damaged"}
    assert cc.load_payload_file(None) is None


def _load_root_cli():
    """Load the repo-root cli.py explicitly — agent-engine/cli/ (the broadcast
    package) would otherwise shadow it when tests run from agent-engine/."""
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "..", "cli.py")
    spec = importlib.util.spec_from_file_location("root_cli", os.path.abspath(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_help_lists_all_commands():
    cli = _load_root_cli()
    for cmd in ("start-server", "generate-report", "run-reengage", "stop-reengage",
                "list-alerts", "trigger-alerts", "approval-request",
                "approval-pending", "approval-decision"):
        try:
            cli.main([cmd, "--help"])
        except SystemExit as e:
            assert e.code == 0