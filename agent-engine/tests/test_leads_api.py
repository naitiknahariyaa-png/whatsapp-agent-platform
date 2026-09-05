"""API tests for the new leads/orders/admin endpoints (Section 3-4)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_leads_and_orders_api():
    import auth  # register User/AuditLog tables BEFORE init_db
    from db import init_db
    await init_db()
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # register an admin-less client user; use dev-create-admin for a quick token
        r = await ac.post("/auth/register", json={
            "email": f"leadapi_{os.urandom(3).hex()}@example.com",
            "password": "TestPass123!", "full_name": "Lead API"})
        tok = r.json().get("access_token")
        h = {"Authorization": f"Bearer {tok}"}

        # list leads for client 1 (may be empty at first)
        r = await ac.get("/clients/1/leads", headers=h)
        assert r.status_code in (200, 403)  # 403 if not admin/owner, 200 if allowed

        # admin overview requires admin role → expect 403 for plain client
        r = await ac.get("/admin/overview", headers=h)
        assert r.status_code == 403

        # profile update on own account
        r = await ac.patch("/api/me/profile", headers=h, json={"tone": "friendly"})
        assert r.status_code in (200, 400)  # 400 if no business linked
