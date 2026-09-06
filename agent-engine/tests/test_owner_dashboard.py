"""Tests: owner WhatsApp commands (D5) + server-rendered dashboard (E)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_owner_command_order_and_mark(monkeypatch):
    import auth  # register User tables before init_db
    from db import init_db, get_orders, list_leads
    await init_db()
    from main import handle_owner_command

    # unknown command -> ignored
    r = await handle_owner_command(1, "919999999999", "hello there")
    assert r["action"] == "ignored"

    # create a lead to work with
    from main import _upsert_lead
    contact, _ = await _upsert_lead(1, "918000000042", "CmdTest")
    assert contact is not None

    # order with rupee symbol + comma
    r = await handle_owner_command(1, "919999999999", f"order {contact.id} ₹1,250 test order")
    assert r["action"] == "order_created", r
    assert r["amount"] == 1250.0

    orders = await get_orders(1, limit=10)
    assert any(o["id"] == r["order_id"] for o in orders)

    # mark won
    r = await handle_owner_command(1, "919999999999", f"mark {contact.id} won")
    assert r["action"] == "lead_marked" and r["lead_status"] == "won"

    # bad amount
    r = await handle_owner_command(1, "919999999999", f"order {contact.id} abc")
    assert r["action"] == "error"

    # non-existent lead rejected
    r = await handle_owner_command(1, "919999999999", "order 999999 500")
    assert r["action"] == "error" and "not found" in r["reason"]


@pytest.mark.asyncio
async def test_dashboard_login_leads_order():
    import auth
    from db import init_db
    await init_db()
    from main import app, _upsert_lead

    # seed an owner user (unique email)
    email = f"dash_{os.urandom(3).hex()}@example.com"
    user = await auth.create_user(email=email, password="DashPass123!",
                                  full_name="Dash", role=auth.Role.ADMIN.value, client_id=None)

    contact, _ = await _upsert_lead(1, "918000000099", "DashLead")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        # not logged in -> login page
        r = await ac.get("/admin/dashboard")
        assert r.status_code == 200 and "Sign in" in r.text

        # bad login
        r = await ac.post("/admin/dashboard/login", data={"email": email, "password": "nope"})
        assert r.status_code == 401

        # good login -> redirect + cookie
        r = await ac.post("/admin/dashboard/login",
                          data={"email": email, "password": "DashPass123!"})
        assert r.status_code == 303
        assert "wap_dashboard" in ac.cookies

        # dashboard home shows clients + stats
        r = await ac.get("/admin/dashboard")
        assert r.status_code == 200 and "Clients" in r.text and "Export CSV" in r.text

        # leads page for client 1 includes the seeded lead
        r = await ac.get("/admin/dashboard/clients/1/leads")
        assert r.status_code == 200 and "DashLead" in r.text

        # create order via dashboard form
        r = await ac.post(f"/admin/dashboard/leads/{contact.id}/order",
                          data={"client_id": "1", "amount": "999", "description": "dash order"})
        assert r.status_code == 303

        # thread page renders
        r = await ac.get(f"/admin/dashboard/leads/{contact.id}/thread?client_id=1")
        assert r.status_code == 200

        # seed a Client row for toggle test (idempotent — another test may have made one)
        from db import Client, async_session
        async with async_session() as s:
            exists = (await s.execute(
                Client.__table__.select().where(Client.id == 1))).first()
            if not exists:
                s.add(Client(id=1, business_name="Test Biz",
                             whatsapp_number="919999999999", vertical="general"))
                await s.commit()

        # toggle subscription (admin)
        r = await ac.post("/admin/dashboard/clients/1/toggle")
        assert r.status_code == 303
        r = await ac.post("/admin/dashboard/clients/1/toggle")  # back on
        assert r.status_code == 303

        # client-role user cannot see other tenants
        u2 = await auth.create_user(email=f"c2_{os.urandom(3).hex()}@example.com",
                                    password="DashPass123!", full_name="C2",
                                    role=auth.Role.CLIENT.value, client_id=1)
        tok2 = auth.create_access_token(u2.id, u2.email, u2.role, u2.client_id)
        async with AsyncClient(transport=transport, base_url="http://t",
                               cookies={"wap_dashboard": tok2}) as ac2:
            r = await ac2.get("/admin/dashboard/clients/2/leads")
            assert r.status_code == 403
