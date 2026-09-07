"""Multi-Tenant-Assistant-AI: tenant scoping, action execution, prompt."""
import asyncio

import pytest

import db
from account_assistant import (
    execute_account_action, extract_action, get_multi_tenant_prompt,
    get_owner_profile, list_accounts, SUGGESTED_VOICE,
)


class FakeUser:
    def __init__(self, role="client", client_id=None):
        self.role = role
        self.client_id = client_id
        self.id = 1
        self.email = "t@t.io"


@pytest.fixture(scope="module")
def setup_db():
    asyncio.run(db.init_db())
    return True


_wa_counter = [9110000000]


def _mk_client(name, vertical="salon", wa=None, plan="trial", active=True):
    async def _go():
        _wa_counter[0] += 1
        async with db.async_session() as s:
            c = db.Client(business_name=name, vertical=vertical,
                          whatsapp_number=wa or f"+{_wa_counter[0]}",
                          plan=plan, is_active=active)
            s.add(c)
            await s.commit()
            await s.refresh(c)
            return c.id
    return asyncio.run(_go())


# ── create_account ───────────────────────────────────────────────────────────
def test_create_account_happy_path(setup_db):
    admin = FakeUser(role="admin")
    out = asyncio.run(execute_account_action({
        "action": "create_account", "business_name": "Sunrise Salon",
        "vertical": "salon", "whatsapp_number": "+15559870001",
        "brand_voice": "playful",
        "welcome_image_url": "https://cdn.example.com/salon.jpg",
    }, admin))
    assert out["ok"] and out["client_id"] > 0

    prof = asyncio.run(get_owner_profile(out["client_id"]))
    assert prof["business_name"] == "Sunrise Salon"
    assert prof["brand_voice"] == "playful"
    assert prof["welcome_image_url"] == "https://cdn.example.com/salon.jpg"
    assert prof["qr_tracking_enabled"] is True


def test_create_account_missing_fields_rejected(setup_db):
    admin = FakeUser(role="admin")
    out = asyncio.run(execute_account_action({
        "action": "create_account", "business_name": "Only Name"}, admin))
    assert not out["ok"] and "vertical" in out["error"]


def test_create_account_duplicate_whatsapp_rejected(setup_db):
    admin = FakeUser(role="admin")
    asyncio.run(execute_account_action({
        "action": "create_account", "business_name": "A", "vertical": "retail",
        "whatsapp_number": "+15559877777"}, admin))
    out = asyncio.run(execute_account_action({
        "action": "create_account", "business_name": "B", "vertical": "retail",
        "whatsapp_number": "+15559877777"}, admin))
    assert not out["ok"] and "already registered" in out["error"]


def test_create_account_non_https_media_dropped(setup_db):
    admin = FakeUser(role="admin")
    out = asyncio.run(execute_account_action({
        "action": "create_account", "business_name": "Media Test",
        "vertical": "retail", "whatsapp_number": "+15559872222",
        "logo_url": "http://insecure.com/l.png"}, admin))
    prof = asyncio.run(get_owner_profile(out["client_id"]))
    assert "logo_url" not in prof


# ── tenant scoping ───────────────────────────────────────────────────────────
def test_update_other_tenant_denied(setup_db):
    cid = _mk_client("Victim Shop", vertical="retail")
    outsider = FakeUser(role="client", client_id=cid + 1000)
    out = asyncio.run(execute_account_action({
        "action": "update_account", "client_id": cid,
        "updates": {"brand_voice": "hacked"}}, outsider))
    assert not out["ok"] and "not your account" in out["error"]


def test_update_own_tenant_allowed(setup_db):
    cid = _mk_client("My Shop", vertical="ca")
    me = FakeUser(role="client", client_id=cid)
    out = asyncio.run(execute_account_action({
        "action": "update_account", "client_id": cid,
        "updates": {"brand_voice": "casual"}}, me))
    assert out["ok"] and out["updated"].get("brand_voice")
    prof = asyncio.run(get_owner_profile(cid))
    assert prof["brand_voice"] == "casual"


def test_update_custom_fields_and_media(setup_db):
    cid = _mk_client("Field Shop", vertical="restaurant")
    me = FakeUser(role="client", client_id=cid)
    out = asyncio.run(execute_account_action({
        "action": "update_account", "client_id": cid,
        "updates": {"custom_fields": {"service_hours": "Mon-Fri 9-5"},
                    "menu_image_url": "https://cdn.f.com/menu.jpg"}}, me))
    assert out["ok"]
    prof = asyncio.run(get_owner_profile(cid))
    assert prof["custom_fields"]["service_hours"] == "Mon-Fri 9-5"
    assert prof["menu_image_url"].startswith("https://")


def test_deactivate_and_delete_scoping(setup_db):
    cid = _mk_client("Doomed Shop")
    me = FakeUser(role="client", client_id=cid)
    out = asyncio.run(execute_account_action(
        {"action": "deactivate_account", "client_id": cid}, me))
    assert out["ok"] and out["is_active"] is False

    out = asyncio.run(execute_account_action(
        {"action": "delete_account", "client_id": cid}, me))
    assert not out["ok"] and "admin-only" in out["error"]
    admin = FakeUser(role="admin")
    out = asyncio.run(execute_account_action(
        {"action": "delete_account", "client_id": cid}, admin))
    assert out["ok"] and out["deleted"]


def test_nonexistent_client_rejected(setup_db):
    me = FakeUser(role="client", client_id=424242)
    out = asyncio.run(execute_account_action(
        {"action": "deactivate_account", "client_id": 424242}, me))
    assert not out["ok"]


def test_list_accounts_scoped(setup_db):
    mine = _mk_client("Visible Shop", vertical="retail")
    _mk_client("Other Shop", vertical="retail")
    me = FakeUser(role="client", client_id=mine)
    out = asyncio.run(list_accounts(me))
    ids = [a["client_id"] for a in out["accounts"]]
    assert mine in ids
    admin = FakeUser(role="admin")
    out_admin = asyncio.run(list_accounts(admin))
    assert len(out_admin["accounts"]) >= 2


def test_extract_action_from_llm_reply():
    reply = """Your new account is ready!
{"action": "create_account", "business_name": "Dental Care Center",
 "vertical": "doctor", "whatsapp_number": "+15551239876", "plan": "trial",
 "brand_voice": "formal"}"""
    a = extract_action(reply)
    assert a and a["action"] == "create_account"
    assert a["brand_voice"] == "formal"
    assert extract_action("no json here") is None
    assert extract_action('{"action":}') is None


def test_suggested_voice_by_vertical():
    assert SUGGESTED_VOICE["doctor"] == "formal"
    assert SUGGESTED_VOICE["salon"] == "playful"


def test_multi_tenant_prompt_contains_workflow(setup_db):
    cid = _mk_client("Prompt Clinic", vertical="doctor")
    prompt = asyncio.run(get_multi_tenant_prompt(cid))
    assert "Multi-Tenant-Assistant-AI" in prompt
    assert "Prompt Clinic" in prompt
    assert "create_account" in prompt and "deactivate_account" in prompt
    assert "VERTICAL GUIDELINES" in prompt  # composes with prompt_builder

    async def _with_contact():
        async with db.async_session() as s:
            c = db.Contact(client_id=cid, phone_number="+919000000001",
                           name="Riya", tags=["vip"])
            s.add(c)
            await s.commit()
            await s.refresh(c)
            return c.id
    contact_id = asyncio.run(_with_contact())
    prompt2 = asyncio.run(get_multi_tenant_prompt(cid, contact_id=contact_id))
    assert "Riya" in prompt2 and "vip" in prompt2