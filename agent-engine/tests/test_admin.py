"""Admin endpoint auth-guard + observability endpoint tests."""
import os
import sys
import pytest
from httpx import AsyncClient, ASGITransport

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from main import app
from db import init_db


@pytest.fixture(scope="module")
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client):
    r = await client.post("/auth/login", json={"email": "adminprobe@example.com", "password": "AdminProbe123!"})
    if r.status_code == 200 and r.json().get("access_token"):
        return r.json()["access_token"]
    r = await client.post("/auth/register", json={"email": "adminprobe@example.com", "password": "AdminProbe123!", "full_name": "Probe"})
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_health_requires_auth(client):
    r = await client.get("/api/admin/health")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_health_forbids_normal_user(client):
    token = await _login(client)
    resp = await client.get("/api/admin/health", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_diagnostic_is_public(client):
    resp = await client.get("/api/diagnostic")
    assert resp.status_code == 200
    assert "database" in resp.json()
