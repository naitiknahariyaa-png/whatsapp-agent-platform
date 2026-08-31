"""Test that the React UI is served at /app and the static mount works."""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_app_serves_react_shell(client):
    """The React+Served dashboard should return the index.html shell."""
    resp = await client.get("/app/")
    assert resp.status_code == 200
    assert "root" in resp.text