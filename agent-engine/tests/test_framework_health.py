"""
Framework Health & Readiness Test Suite
Tests core framework components: auth, business profile, catalog, orders, themes.
"""
import sys
import os
import pytest
from fastapi.testclient import TestClient

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _AGENT_DIR)

_SERVICES_DIR = os.path.abspath(os.path.join(_AGENT_DIR, "..", "services"))
if _SERVICES_DIR not in sys.path:
    sys.path.insert(0, _SERVICES_DIR)

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def auth_token(client):
    """Register or login a test user."""
    resp = client.post("/auth/login", json={
        "email": "test@example.com", "password": "TestPassword123!"
    })
    if resp.status_code == 200 and resp.json().get("access_token"):
        return resp.json()["access_token"]
    resp = client.post("/auth/register", json={
        "email": "test@example.com", "password": "TestPassword123!",
        "full_name": "Test User"
    })
    assert resp.status_code == 200, f"Register failed: {resp.text}"
    return resp.json()["access_token"]


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_stats_endpoint(client):
    resp = client.get("/stats")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_sitemap_endpoint(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "urlset" in resp.text


def test_robots_endpoint(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert "User-agent" in resp.text


def test_auth_me(client, auth_token):
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@example.com"


def test_auth_me_unauthorized(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_business_types(client):
    resp = client.get("/api/business/types")
    assert resp.status_code == 200
    assert "types" in resp.json()


def test_business_template(client):
    resp = client.get("/api/business/restaurant/template")
    assert resp.status_code == 200
    assert "welcome" in resp.json()


def test_create_business_unauthenticated(client):
    resp = client.post("/api/business/create", json={
        "business_type": "restaurant", "name": "Test Restaurant"
    })
    assert resp.status_code == 401


def test_themes_listing(client):
    resp = client.get("/api/themes")
    assert resp.status_code == 200
    assert len(resp.json()["themes"]) >= 10


def test_frontend_dashboard_updated():
    dashboard_path = os.path.join(_AGENT_DIR, "..", "frontend", "dashboard.html")
    assert os.path.exists(dashboard_path)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "nav-toggle" in content
    assert "toggleSidebar" in content
    count = content.count("function showSection(name)")
    assert count == 1, f"Expected 1 showSection, found {count}"


def test_frontend_dashboard_has_analytics():
    dashboard_path = os.path.join(_AGENT_DIR, "..", "frontend", "dashboard.html")
    assert os.path.exists(dashboard_path)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "section-analytics" in content
    assert "revenueChart" in content
    assert "funnelChart" in content
    assert "section-keys" in content
    assert "section-whatsapp" in content
    assert "chart.js" in content


def test_frontend_index_seo():
    index_path = os.path.join(_AGENT_DIR, "..", "frontend", "index.html")
    assert os.path.exists(index_path)
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "og:title" in content
    assert "og:description" in content
    assert "twitter:card" in content
    assert "application/ld+json" in content
    assert "keywords" in content.lower()
    assert "canonical" in content


def test_frontend_sitemap_exists():
    sitemap_path = os.path.join(_AGENT_DIR, "..", "frontend", "sitemap.xml")
    assert os.path.exists(sitemap_path)


def test_frontend_robots_exists():
    robots_path = os.path.join(_AGENT_DIR, "..", "frontend", "robots.txt")
    assert os.path.exists(robots_path)


def test_frontend_terms_exists():
    terms_path = os.path.join(_AGENT_DIR, "..", "frontend", "terms.html")
    assert os.path.exists(terms_path)
    with open(terms_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Terms & Conditions" in content
    assert "secondary phone" in content.lower() or "secondary number" in content.lower()
    assert "FREE" in content


def test_frontend_privacy_exists():
    privacy_path = os.path.join(_AGENT_DIR, "..", "frontend", "privacy.html")
    assert os.path.exists(privacy_path)
    with open(privacy_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Privacy Policy" in content
    assert "encrypted" in content.lower()


def test_dashboard_has_health_section():
    dashboard_path = os.path.join(_AGENT_DIR, "..", "frontend", "dashboard.html")
    assert os.path.exists(dashboard_path)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "section-health" in content
    assert "Account Health" in content
    assert "chat-toggle" in content
    assert "checkHealth" in content
    assert "section-analytics" in content


def test_sitemap_has_terms_privacy():
    sitemap_path = os.path.join(_AGENT_DIR, "..", "frontend", "sitemap.xml")
    assert os.path.exists(sitemap_path)
    with open(sitemap_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "terms.html" in content
    assert "privacy.html" in content


def test_frontend_onboarding_premium():
    onboarding_path = os.path.join(_AGENT_DIR, "..", "frontend", "onboarding.html")
    assert os.path.exists(onboarding_path)
    with open(onboarding_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Premium Services" in content
    assert "qr" in content.lower()
    assert "whatsapp" in content.lower()


def test_figma_service_exists():
    figma_path = os.path.join(_SERVICES_DIR, "figma_integration.py")
    assert os.path.exists(figma_path)


def test_telegram_bridge_exists():
    telegram_path = os.path.join(_AGENT_DIR, "telegram_bridge.py")
    assert os.path.exists(telegram_path)


def test_figma_status_endpoint(client):
    resp = client.get("/api/figma/status")
    assert resp.status_code == 200
    assert "configured" in resp.json()


def test_secrets_manager():
    """Test that the secrets manager works and doesn't expose values."""
    from secrets_manager import secrets
    assert secrets.is_configured("GROQ_API_KEY")
    redacted = secrets.redact("supersecretvalue123")
    assert "supersecretvalue123" not in redacted
    assert "..." in redacted
    assert len(redacted) < len("supersecretvalue123")
    summary = secrets.summary()
    assert isinstance(summary, dict)
    assert all(isinstance(v, bool) for v in summary.values())


def test_whatsapp_qr_requires_auth(client):
    resp = client.get("/api/whatsapp/qr")
    assert resp.status_code == 401


def test_whatsapp_status_requires_auth(client):
    resp = client.get("/api/whatsapp/status")
    assert resp.status_code == 401


def test_api_keys_requires_auth(client):
    resp = client.get("/api/keys")
    assert resp.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
