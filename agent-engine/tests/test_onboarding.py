"""
Smoke tests for the multi-tenant owner onboarding router (Section 2).

These tests use the existing conftest fixtures (isolated SQLite DB +
in-memory metric stores) so they don't touch real Postgres or Redis.

NOTE: To actually run these, the pre-existing `pool_size` issue in
`db.py` (SQLite engine rejects pool args) must be fixed first. Until
then, the tests serve as a contract spec for what the API should do.
"""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
async def client():
    """Yield a TestClient against an isolated app instance."""
    # Importing main.py triggers the full app + DB init. We isolate
    # the DB via DATABASE_URL already set by conftest.py.
    from main import app
    from db import init_db
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_owner_minimum_fields(client):
    resp = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Ravi Ka Dhaba",
            "owner_name": "Ravi",
            "owner_phone": "919876543210",
            "business_category": "restaurant",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["business_name"] == "Ravi Ka Dhaba"
    assert data["business_category"] == "restaurant"
    assert data["brand_voice"] == "casual"  # default
    assert "hi" in data["languages"]


@pytest.mark.asyncio
async def test_create_owner_rejects_duplicate_phone(client):
    payload = {
        "business_name": "A",
        "owner_name": "X",
        "owner_phone": "919999999999",
    }
    r1 = await client.post("/api/onboarding/owners", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/onboarding/owners", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_create_owner_validates_category(client):
    r = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "X",
            "owner_name": "Y",
            "owner_phone": "911111111111",
            "business_category": "not_a_real_category",
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_add_and_list_catalog(client):
    # Create owner
    or_ = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Cafe",
            "owner_name": "Sam",
            "owner_phone": "918888888888",
            "business_category": "restaurant",
        },
    )
    owner_id = or_.json()["id"]

    # Add 2 items
    for it in [
        {"name": "Vada Pav", "price": 30, "prep_time_minutes": 5, "prep_time_tier": "fast", "tags": ["veg"]},
        {"name": "Paneer Butter Masala", "price": 220, "prep_time_minutes": 20, "prep_time_tier": "normal", "tags": ["veg", "popular"]},
    ]:
        r = await client.post(f"/api/onboarding/owners/{owner_id}/catalog", json=it)
        assert r.status_code == 201, r.text

    listing = await client.get(f"/api/onboarding/owners/{owner_id}/catalog")
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_rank_catalog_budget_and_time(client):
    """The Section 3 query: budget=250, prep<=15, only fast tier."""
    or_ = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Cafe",
            "owner_name": "Sam",
            "owner_phone": "917777777777",
            "business_category": "restaurant",
        },
    )
    owner_id = or_.json()["id"]

    for it in [
        {"name": "Vada Pav", "price": 30, "prep_time_minutes": 5, "prep_time_tier": "fast", "priority": 10},
        {"name": "Veg Thali", "price": 200, "prep_time_minutes": 12, "prep_time_tier": "fast", "priority": 5},
        {"name": "Paneer", "price": 220, "prep_time_minutes": 20, "prep_time_tier": "normal", "priority": 5},
        {"name": "Pizza", "price": 400, "prep_time_minutes": 25, "prep_time_tier": "slow", "priority": 1},
    ]:
        await client.post(f"/api/onboarding/owners/{owner_id}/catalog", json=it)

    r = await client.get(
        f"/api/onboarding/owners/{owner_id}/catalog/rank",
        params={"budget_max": 250, "prep_time_max_minutes": 15, "tier": "fast", "relax": True},
    )
    assert r.status_code == 200
    items = r.json()
    # Vada Pav (priority 10) and Veg Thali (priority 5, under budget) match
    # Pizza is over budget, Paneer is over time
    names = [i["name"] for i in items]
    assert "Vada Pav" in names
    assert "Veg Thali" in names
    assert "Pizza" not in names
    assert "Paneer" not in names
    # First item must be the highest-priority one
    assert items[0]["name"] == "Vada Pav"


@pytest.mark.asyncio
async def test_rank_relaxes_time_first_by_default(client):
    """With prefer_speed policy, if no item matches time cap, drop it."""
    or_ = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Cafe",
            "owner_name": "Sam",
            "owner_phone": "916666666666",
            "business_category": "restaurant",
        },
    )
    owner_id = or_.json()["id"]

    # Set policy = prefer_speed
    await client.put(
        f"/api/onboarding/owners/{owner_id}/policies",
        json={"relaxation_policy": "prefer_speed"},
    )
    # Add one item that exceeds 15-min cap
    await client.post(
        f"/api/onboarding/owners/{owner_id}/catalog",
        json={"name": "Slow Biryani", "price": 200, "prep_time_minutes": 30, "prep_time_tier": "normal"},
    )

    # Strict: no items match
    r = await client.get(
        f"/api/onboarding/owners/{owner_id}/catalog/rank",
        params={"budget_max": 250, "prep_time_max_minutes": 15, "relax": True},
    )
    items = r.json()
    # With prefer_speed + relax, the time cap is dropped, so Biryani should appear
    assert any(i["name"] == "Slow Biryani" for i in items)


@pytest.mark.asyncio
async def test_api_key_encrypted_at_rest(client):
    or_ = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Shop",
            "owner_name": "P",
            "owner_phone": "915555555555",
            "business_category": "retail",
        },
    )
    owner_id = or_.json()["id"]

    r = await client.post(
        f"/api/onboarding/owners/{owner_id}/keys",
        json={
            "provider": "razorpay",
            "key_id": "rzp_test_abc",
            "key": "supersecret-razorpay-key-12345",
            "secret": "supersecret-razorpay-secret-67890",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert "supersecret" not in body["key_mask"]  # plaintext never in response
    assert "****" in body["key_mask"]  # mask is shown

    # GET should never return plaintext
    r2 = await client.get(f"/api/onboarding/owners/{owner_id}/keys")
    assert r2.status_code == 200
    keys = r2.json()
    for k in keys:
        assert "supersecret" not in str(k)  # never leaks
        assert "****" in k["key_mask"]


@pytest.mark.asyncio
async def test_complete_onboarding_links_client(client):
    or_ = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Final",
            "owner_name": "Z",
            "owner_phone": "914444444444",
            "business_category": "salon",
        },
    )
    owner_id = or_.json()["id"]
    r = await client.post(f"/api/onboarding/owners/{owner_id}/onboard/complete")
    assert r.status_code == 200
    body = r.json()
    assert body["onboarded_at"] is not None
    # Idempotent
    r2 = await client.post(f"/api/onboarding/owners/{owner_id}/onboard/complete")
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_tenant_isolation_owner_not_found(client):
    r = await client.get("/api/onboarding/owners/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_wizard_state_endpoint(client):
    or_ = await client.post(
        "/api/onboarding/owners",
        json={
            "business_name": "Full",
            "owner_name": "Q",
            "owner_phone": "913333333333",
            "business_category": "clinic",
        },
    )
    owner_id = or_.json()["id"]
    r = await client.get(f"/api/onboarding/owners/{owner_id}")
    assert r.status_code == 200
    state = r.json()
    assert state["owner"]["business_name"] == "Full"
    assert state["catalog"] == []
    assert state["policy"] is None
    assert state["keys"] == []
    assert state["catalog_count"] == 0
