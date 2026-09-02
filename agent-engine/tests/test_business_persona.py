import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from cli_commands import build_business_system_prompt  # noqa: E402


SAMPLE = {
    "name": "Madhuri's Grocery",
    "business_type": "retail grocery",
    "description": "Fresh produce, daily milk delivery and local staples.",
    "address": "Indiranagar, Bengaluru, Karnataka",
    "contact_phone": "+919876543210",
    "contact_email": "madhuri@grocery.in",
    "working_hours": {"summary": "Mon-Sat 09:00-19:00"},
    "payment_methods": ["upi", "cash", "card"],
    "delivery_enabled": True,
    "delivery_radius_km": 5,
    "welcome_message": "Namaste! Welcome to Madhuri's Grocery.",
}


def test_persona_contains_real_business_facts():
    out = build_business_system_prompt(SAMPLE, catalog=[
        {"name": "Fresh vegetables", "price": 1},
        {"name": "Daily milk delivery", "price": 1},
    ], owner_name="Madhuri Patel")
    assert "Madhuri's Grocery" in out
    assert "Fresh vegetables" in out and "Daily milk delivery" in out
    assert "Bengaluru" in out and "Karnataka" in out
    assert "Mon-Sat 09:00-19:00" in out
    assert "Madhuri Patel" in out
    assert "+919876543210" in out and "madhuri@grocery.in" in out
    assert "answer AS IF YOU WERE THE BUSINESS ITSELF" in out


def test_persona_graceful_without_profile():
    out = build_business_system_prompt({}, catalog=[], owner_name="")
    # must not crash and must contain a sensible fallback name
    assert "our business" in out
    assert "business-setup" in out  # prompts the owner to fill the form


def test_persona_uses_catalog_when_no_explicit_services():
    out = build_business_system_prompt(
        {"name": "X", "business_type": "cafe"},
        catalog=[{"name": "Cold coffee", "price": 90}, {"name": "Pasta", "price": 190}])
    assert "Cold coffee" in out and "Pasta" in out


def test_template_file_exists_and_formats():
    import pathlib
    root = pathlib.Path(ROOT) / "agent-engine"
    assert (root / "system_prompt_template.txt").exists()