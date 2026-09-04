"""Subscription switch tests: orchestrator gate + admin endpoint."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_inactive_client_gets_offline_message(monkeypatch):
    from orchestrator import AgentOrchestrator
    from db import Client

    o = AgentOrchestrator()

    class FakeResult:
        def __init__(self, v):
            self._v = v
        def scalar_one_or_none(self):
            return self._v

    class FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def execute(self, q):
            # the subscription select targets Client.is_active
            if "is_active" in str(q):
                return FakeResult(False)
            raise AssertionError("no further queries expected after offline reply")
        def add(self, *a, **k):
            pass

    import orchestrator as orch_mod
    async def fake_get_session():
        yield FakeSession()
    monkeypatch.setattr(orch_mod, "get_session", fake_get_session)

    class FakeSM:
        async def is_human_takeover(self, cid, phone):
            return False

    monkeypatch.setattr(orch_mod, "_safe_call", lambda *a, **k: FakeSM())
    # stop after the gate: make save_message a no-op so nothing else runs
    async def fake_save(*a, **k):
        return None
    monkeypatch.setattr(orch_mod, "save_message", fake_save)

    reply = await o.process_message("919000000009", "hello", client_id=1)
    assert reply == ("This business's AI assistant is temporarily offline. "
                     "Please contact the business owner directly.")


@pytest.mark.asyncio
async def test_admin_subscription_endpoints():
    # Import the app FIRST so all models (users, clients, ...) register in
    # Base.metadata; then init_db() creates every table.
    from main import app
    from db import init_db, async_session, Client
    from sqlalchemy import select
    await init_db()  # create all tables in the isolated test DB
    # seed a client (id 1)
    async with async_session() as seed:
        if not (await seed.execute(select(Client.id).where(Client.id == 1))).scalar_one_or_none():
            seed.add(Client(id=1, business_name="TestBiz", vertical="general",
                            whatsapp_number="919000000000"))
            await seed.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # register -> CLIENT role; admin gate should reject with 403
        email = f"sub_e2e_{os.urandom(3).hex()}@example.com"
        r = await ac.post("/auth/register", json={
            "email": email, "password": "TestPass123!", "full_name": "Sub"})
        tok = r.json().get("access_token")
        r2 = await ac.post("/api/admin/clients/1/subscription",
                           headers={"Authorization": f"Bearer {tok}"},
                           json={"is_active": False})
        assert r2.status_code == 403  # non-admin blocked

        # confirm DB is untouched (still active) by a non-admin
        async with async_session() as s2:
            cl = (await s2.execute(select(Client).where(Client.id == 1))).scalar_one()
            assert cl.is_active is True
