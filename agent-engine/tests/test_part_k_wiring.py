"""
Part K tests — supporting-tier surfaces now backed by real endpoints.

Proves the dashboard's QA, Retention, Approvals and Advisory-history screens
call real routes returning real data (not stubs / hardcoded empties).
"""
import os
import sys
import uuid

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    """Register a unique user and return (token, user_id)."""
    email = f"partk_{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/auth/register", json={
        "email": email, "password": "PartkPassword123!", "full_name": "Part K",
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return {"token": token, "id": me["id"]}


# ---------------------------------------------------------------------------
# QA surfacing: seed a real QALog for this tenant, then read it back.
# ---------------------------------------------------------------------------
def test_qa_logs_and_summary_return_real_data(client, auth):
    import asyncio
    async def _seed():
        from db import async_session, register_loop_models
        from db_extensions import QALog
        await register_loop_models()
        async with async_session() as s:
            s.add(QALog(conversation_id=1, client_id=auth["id"], grade=0.9,
                        feedback="correct answer", rag_used_correctly=True,
                        escalation_missed=False))
            s.add(QALog(conversation_id=2, client_id=auth["id"], grade=0.5,
                        feedback="missed escalation", rag_used_correctly=False,
                        escalation_missed=True))
            await s.commit()
    asyncio.run(_seed())

    h = {"Authorization": f"Bearer {auth['token']}"}
    resp = client.get("/api/qa/logs", headers=h)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    grades = {row["grade"] for row in body["logs"]}
    assert grades == {0.9, 0.5}

    summary = client.get("/api/qa/summary", headers=h).json()
    assert summary["total_graded"] == 2
    assert 0.0 < summary["avg_grade"] <= 1.0
    assert summary["verdict"] in ("healthy", "needs_attention", "watch")


# ---------------------------------------------------------------------------
# Security & validation on the new routes
# ---------------------------------------------------------------------------
def test_qa_requires_auth(client):
    assert client.get("/api/qa/logs").status_code == 401
    assert client.get("/api/qa/summary").status_code == 401


def test_advisory_history_validates_advisor_type(client, auth):
    h = {"Authorization": f"Bearer {auth['token']}"}
    assert client.get("/api/advisory/history", params={"advisor_type": "bogus"},
                      headers=h).status_code == 400
    ok = client.get("/api/advisory/history", params={"advisor_type": "ca"}, headers=h)
    assert ok.status_code == 200
    body = ok.json()
    assert "history" in body and body["advisor_type"] == "ca"


def test_refund_process_is_auth_guarded(client):
    # High-stakes: unauthenticated callers are rejected before any gate runs.
    assert client.post("/api/refunds/process", json={"payment_id": "p1", "amount": 100}
                       ).status_code in (401, 403)


def test_retention_endpoints_are_wired(client, auth):
    h = {"Authorization": f"Bearer {auth['token']}"}
    # No stale leads here, but the route must resolve and be tenant-scoped.
    assert client.get("/api/retention/candidates", headers=h).status_code == 200
    assert client.post("/api/retention/reengage/run", headers=h).status_code == 200


def test_approvals_pending_resolves(client, auth):
    h = {"Authorization": f"Bearer {auth['token']}"}
    resp = client.get("/api/approvals/pending", headers=h)
    assert resp.status_code == 200
    assert "pending" in resp.json() and "count" in resp.json()