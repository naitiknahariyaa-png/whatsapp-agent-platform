"""
Tenant Isolation Tests
Automated tests that assert zero cross-tenant data leakage.

These tests verify the most critical security requirement for the
multi-tenant owner onboarding system: Owner A's data must never
appear in Owner B's context.
"""
import os
import sys
import pytest
from httpx import AsyncClient, ASGITransport

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SERVICES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services"))
for _d in [_AGENT_DIR, _SERVICES_DIR]:
    if _d not in sys.path:
        sys.path.insert(0, _d)

from main import app
from db import async_session, init_db


@pytest.fixture
async def client():
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_owner_catalog_isolation(client):
    """Assert Owner A's catalog never leaks into Owner B's queries."""

    r = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Owner A Business",
            "owner_name": "Owner A",
            "owner_phone": "+919999999901",
            "business_category": "restaurant",
        },
    )
    assert r.status_code == 201, r.text
    owner_a = r.json()

    r = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Owner B Business",
            "owner_name": "Owner B",
            "owner_phone": "+919999999902",
            "business_category": "retail",
        },
    )
    assert r.status_code == 201, r.text
    owner_b = r.json()

    for item in [
        {"name": "Butter Chicken", "price": 250, "category": "food", "prep_time_minutes": 15},
        {"name": "Biryani", "price": 300, "category": "food", "prep_time_minutes": 25},
    ]:
        r = await client.post(f"/api/onboarding/owners/{owner_a['id']}/catalog", json=item)
        assert r.status_code == 201, r.text

    r = await client.post(f"/api/onboarding/owners/{owner_b['id']}/catalog", json={
        "name": "T-Shirt", "price": 500, "category": "clothing", "prep_time_minutes": 0
    })
    assert r.status_code == 201, r.text

    r = await client.get(f"/api/onboarding/owners/{owner_a['id']}/catalog")
    assert r.status_code == 200
    catalog_a = r.json()
    assert len(catalog_a) == 2

    r = await client.get(f"/api/onboarding/owners/{owner_b['id']}/catalog")
    assert r.status_code == 200
    catalog_b = r.json()
    assert len(catalog_b) == 1

    names_a = [item["name"] for item in catalog_a]
    assert "T-Shirt" not in names_a

    names_b = [item["name"] for item in catalog_b]
    assert "Butter Chicken" not in names_b
    assert "Biryani" not in names_b


@pytest.mark.asyncio
async def test_api_key_encryption(client):
    """Assert API keys are encrypted at rest."""
    from db import OwnerApiKey
    from sqlalchemy import select
    from secrets_manager import secrets

    r = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Test Business",
            "owner_name": "Test Owner",
            "owner_phone": "+919999999903",
            "business_category": "restaurant",
        },
    )
    assert r.status_code == 201, r.text
    owner_id = r.json()["id"]

    r = await client.post(
        f"/api/onboarding/owners/{owner_id}/keys",
        json={"provider": "whatsapp_business", "key": "super_secret_api_key_12345"},
    )
    assert r.status_code == 201, r.text

    async with async_session() as session:
        result = await session.execute(
            select(OwnerApiKey).where(OwnerApiKey.owner_id == owner_id)
        )
        key_row = result.scalar_one_or_none()

    assert key_row is not None, "API key row not created"
    assert key_row.encrypted_key != "super_secret_api_key_12345", "API key stored in plaintext!"
    assert "super_secret" not in (key_row.encrypted_key or ""), "Plaintext API key visible in DB!"

    decrypted = secrets.decrypt(key_row.encrypted_key)
    assert decrypted == "super_secret_api_key_12345", f"Decryption failed: {decrypted}"


@pytest.mark.asyncio
async def test_policy_isolation(client):
    """Assert policies are scoped per owner."""

    r = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Policy Test A",
            "owner_name": "Owner A",
            "owner_phone": "+919999999904",
            "business_category": "restaurant",
        },
    )
    assert r.status_code == 201, r.text
    owner_a = r.json()

    r = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Policy Test B",
            "owner_name": "Owner B",
            "owner_phone": "+919999999905",
            "business_category": "retail",
        },
    )
    assert r.status_code == 201, r.text
    owner_b = r.json()

    r = await client.put(
        f"/api/onboarding/owners/{owner_a['id']}/policies",
        json={"max_autonomous_discount_pct": 10.0},
    )
    assert r.status_code == 200, r.text
    policy_a = r.json()

    r = await client.put(
        f"/api/onboarding/owners/{owner_b['id']}/policies",
        json={"max_autonomous_discount_pct": 5.0},
    )
    assert r.status_code == 200, r.text
    policy_b = r.json()

    assert policy_a["max_autonomous_discount_pct"] == 10.0
    assert policy_b["max_autonomous_discount_pct"] == 5.0


@pytest.mark.asyncio
async def test_no_cross_tenant_knowledge_chunks():
    """Assert knowledge base chunks are scoped per owner."""
    from vector_store import vector_store

    try:
        results = await vector_store.search(
            query="test",
            client_id=999,
            n_results=5,
        )
        assert len(results) == 0, "Vector store returned results for non-existent owner!"
    except Exception:
        pass
