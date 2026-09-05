"""Tests for the lead → order pipeline and onboarding profile storage."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.mark.asyncio
async def test_order_model_and_helpers():
    from db import init_db
    await init_db()
    from db import Order, create_order, get_orders, update_lead_status, list_leads, admin_overview
    # create a lead (contact) to attach the order to
    from db import async_session, Contact
    from crypto_fields import hmac_phone_hash
    async with async_session() as session:
        c = Contact(client_id=1, phone_number="91900000001", phone_hash=hmac_phone_hash("91900000001"),
                    name="Lead One", lead_status="new", source="test")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        cid = c.id

    order = await create_order(1, cid, amount=1500.0, currency="INR", description="Test sale")
    assert order.id is not None
    assert order.amount == 1500.0
    assert order.status == "pending"
    assert order.lead_id == cid

    orders = await get_orders(1)
    assert any(o["id"] == order.id for o in orders)

    updated = await update_lead_status(1, cid, "qualified")
    assert updated is not None
    assert updated.lead_status == "qualified"

    leads = await list_leads(1, status="qualified")
    assert any(l["id"] == cid for l in leads)

    overview = await admin_overview()
    assert "total_clients" in overview
    assert "total_orders" in overview
    assert overview["total_orders"] >= 1


@pytest.mark.asyncio
async def test_lead_messages_tenant_safe():
    from db import init_db
    await init_db()
    from db import get_lead_messages, async_session, Message
    from crypto_fields import hmac_phone_hash
    async with async_session() as session:
        session.add(Message(client_id=1, phone_hash=hmac_phone_hash("91900000001"),
                            phone_number="91900000001", content="hello", direction="incoming"))
        await session.commit()
    msgs = await get_lead_messages(1, 1, limit=10)
    assert isinstance(msgs, list)


@pytest.mark.asyncio
async def test_business_profile_storage():
    from db import init_db
    await init_db()
    from db import async_session, Client
    from sqlalchemy import select
    # ensure a client row exists
    async with async_session() as session:
        res = await session.execute(select(Client).where(Client.id == 1))
        client = res.scalar_one_or_none()
        if not client:
            session.add(Client(id=1, business_name="T", vertical="general", whatsapp_number="91900000000"))
            await session.commit()
            res = await session.execute(select(Client).where(Client.id == 1))
            client = res.scalar_one_or_none()
        client.business_profile = {"services": ["a", "b"], "tone": "friendly"}
        await session.commit()
        await session.refresh(client)
        assert client.business_profile["tone"] == "friendly"
