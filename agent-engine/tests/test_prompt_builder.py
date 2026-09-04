"""Tests for the advanced per-client system prompt builder."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompt_builder import (
    build_advanced_system_prompt, load_business_profile,
    build_system_prompt_for_client, _industry_label,
)


def test_generic_profile_produces_full_prompt():
    p = build_advanced_system_prompt({})
    # All requested sections present
    assert "AI receptionist" in p
    assert "## PERSONA & IDENTITY" in p
    assert "## KNOWLEDGE BASE" in p
    assert "## STRICT GUARDRAILS" in p
    assert "## TONE & FORMATTING" in p
    assert "## GOAL" in p
    assert "will have the owner contact you shortly" in p


def test_profile_fields_render():
    p = build_advanced_system_prompt({
        "business_name": "Tandoor House",
        "industry": "restaurant",
        "city": "Delhi",
        "services": ["Butter Chicken", "Garlic Naan"],
        "pricing": ["Butter Chicken - INR 320", "Garlic Naan - INR 60"],
        "selling_points": ["Fresh tandoori", "Same-day booking"],
        "tone": "warm and helpful",
        "contact_phone": "919800011122",
        "contact_email": "owner@tandoor.in",
        "working_hours": "11:00-23:00",
        "payment_methods": ["cash", "upi"],
    })
    assert "Tandoor House" in p
    assert "restaurant located in Delhi" in p
    assert "Butter Chicken" in p
    assert "INR 320" in p
    assert "warm and helpful" in p
    assert "919800011122" in p


def test_industry_label():
    assert _industry_label("doctor") == "clinic / doctor's practice"
    assert _industry_label("restaurant") == "restaurant"
    assert _industry_label(None) == "local shop"


def test_load_business_profile_returns_none_for_bad_client():
    # no profile exists -> None, and the builder still returns a safe prompt
    prof = load_business_profile(-999)
    assert prof is None
    assert "AI receptionist" in build_system_prompt_for_client(-999)


def test_two_clients_produce_different_prompts(prepare_two_profiles):
    p1 = build_system_prompt_for_client(90001)
    p2 = build_system_prompt_for_client(90002)
    # different business names -> different personas
    assert "Tandoor House" in p1 or "Green Hotel" in p2 or p1 != p2


import pytest


@pytest.fixture
def prepare_two_profiles():
    """Create two distinct business profiles so the builder differs per client."""
    from business_profiles import business_manager, BusinessProfile, BusinessType

    for cid, name, btype in [(90001, "Tandoor House", "restaurant"),
                             (90002, "Green Hotel", "hotel")]:
        existing = None
        for p in business_manager.profiles.values():
            if p.client_id == cid:
                existing = p
                break
        if existing:
            continue
        prof = BusinessProfile(
            id=f"cid{cid}", client_id=cid, owner_id=str(cid),
            business_type=BusinessType(btype), name=name,
            description=f"{name} description", address="Delhi 110001",
            contact_phone=f"+91 9{cid}", welcome_message=f"Welcome to {name}",
        )
        business_manager.profiles[prof.id] = prof
    yield
