"""Multi-tenancy isolation tests."""
import pytest

from crypto_fields import hmac_phone_hash


@pytest.mark.asyncio
async def test_save_message_scoped_by_client(db_session):
    from db import save_message, get_conversation_history

    phone = "+919999999999"
    await save_message(db_session, phone, "hi client1", client_id=1)
    await save_message(db_session, phone, "hi client2", client_id=2)

    hist1 = await get_conversation_history(db_session, phone, client_id=1)
    hist2 = await get_conversation_history(db_session, phone, client_id=2)
    assert [m.content for m in hist1] == ["hi client1"]
    assert [m.content for m in hist2] == ["hi client2"]


@pytest.mark.asyncio
async def test_upsert_contact_scoped_by_client(db_session):
    from db import upsert_contact, Contact
    from sqlalchemy import select
    from crypto_fields import hmac_phone_hash

    phone = "+918888888888"
    c1 = await upsert_contact(db_session, phone, client_id=1, name="A")
    c2 = await upsert_contact(db_session, phone, client_id=2, name="B")
    assert c1.id != c2.id
    assert c1.client_id == 1 and c2.client_id == 2

    phone_h = hmac_phone_hash(phone)
    res = await db_session.execute(select(Contact).where(Contact.phone_hash == phone_h))
    contacts = res.scalars().all()
    # Two physically separate contacts, one per tenant
    assert len(contacts) == 2


@pytest.mark.asyncio
async def test_get_bookings_scoped_by_client(db_session):
    from db import create_booking, get_bookings

    await create_booking(db_session, client_id=1, business_id="biz1", business_type="restaurant", extracted={"intent": "booking_request"})
    await create_booking(db_session, client_id=2, business_id="biz2", business_type="restaurant", extracted={"intent": "booking_request"})
    b1 = await get_bookings(client_id=1)
    b2 = await get_bookings(client_id=2)
    assert len(b1) == 1 and b1[0]["business_id"] == "biz1"
    assert len(b2) == 1 and b2[0]["business_id"] == "biz2"
    assert all(b["client_id"] == 1 for b in b1)
    assert all(b["client_id"] == 2 for b in b2)
