"""
Multi-Tenant-Assistant-AI — account setup/switch/update/delete assistant.

The LLM proposes JSON actions; this module validates them against the
authenticated user's tenant scope and executes them on the real DB:

  {"action": "create_account", "business_name": ..., "vertical": ..., ...}
  {"action": "update_account", "client_id": N, "updates": {...}}
  {"action": "deactivate_account", "client_id": N}
  {"action": "delete_account", "client_id": N}      # admin only
  {"action": "switch_account", "client_id": N}

Security: every mutation is scoped — a client-role user may only touch the
client bound to their User.client_id; platform admins (role=admin) may touch
any. No other tenant's data is ever returned to the LLM.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("account_assistant")

_CREATE_TIMEOUT = 15  # seconds, LLM call guard

SUGGESTED_VOICE = {
    "doctor": "formal", "salon": "playful", "restaurant": "casual",
    "retail": "casual", "legal": "formal", "ca": "formal",
    "education": "formal", "hotel": "casual", "general": "casual",
}

_REQUIRED_FIELDS = ("business_name", "vertical", "whatsapp_number")
_MEDIA_KEYS = ("welcome_image_url", "gallery_images", "menu_image_url",
               "product_images", "logo_url")
_UPDATABLE_KEYS = ("business_name", "vertical", "whatsapp_number", "plan",
                   "brand_voice", "business_hours", "custom_fields") + _MEDIA_KEYS


# ── Profile assembly ─────────────────────────────────────────────────────────
async def get_owner_profile(client_id: int) -> Optional[Dict[str, Any]]:
    """Owner profile dict in the documented schema (never crosses tenants)."""
    from db import async_session, Client
    async with async_session() as session:
        c = await session.get(Client, int(client_id))
        if not c:
            return None
        bp = c.business_profile if isinstance(c.business_profile, dict) else {}
        return {
            "client_id": c.id,
            "business_name": c.business_name,
            "vertical": c.vertical,
            "whatsapp_number": c.whatsapp_number,
            "plan": c.plan,
            "brand_voice": bp.get("brand_voice", "formal"),
            "qr_tracking_enabled": bool(c.qr_tracking_enabled),
            "is_active": bool(c.is_active),
            "custom_fields": {k: v for k, v in bp.items()
                              if k not in ("menu", "brand_voice", "languages",
                                           "business_hours", "currency")},
            **{k: bp[k] for k in _MEDIA_KEYS if bp.get(k)},
        }


async def get_multi_tenant_prompt(client_id: int,
                                  contact_id: Optional[int] = None) -> str:
    """Assemble the Multi-Tenant-Assistant system prompt for one account."""
    profile = await get_owner_profile(client_id) or {}
    contact_ctx: Dict[str, Any] = {}
    if contact_id:
        from db import async_session, Contact
        async with async_session() as session:
            contact = await session.get(Contact, int(contact_id))
            if contact and contact.client_id == int(client_id):
                tags = contact.tags if isinstance(contact.tags, list) else []
                contact_ctx = {"name": contact.name or "",
                               "phone_number": contact.phone_number or "",
                               "tags": tags}

    from prompt_builder import _vertical_guidelines, _media_fields_block
    guidelines = _vertical_guidelines(profile.get("vertical", ""), profile)
    media = _media_fields_block(profile)

    return f"""You are Multi-Tenant-Assistant-AI, a virtual administrator for a multi-account WhatsApp platform.

Owner profile (JSON):
{json.dumps(profile, ensure_ascii=False, default=str)}

Contact context (JSON, optional):
{json.dumps(contact_ctx, ensure_ascii=False, default=str)}

--- Business-specific guidelines ---
{guidelines}

Media you may send (allowlist):
{media}

--- Standard workflow ---
1. New account: collect business_name, vertical, whatsapp_number; suggest brand_voice
   ({json.dumps(SUGGESTED_VOICE)}). Confirm the data back to the user, then output ONLY this JSON:
   {{"action": "create_account", "business_name": "...", "vertical": "...",
     "whatsapp_number": "+E164", "plan": "trial", "brand_voice": "...",
     "welcome_image_url": ""}}
2. Active context: when the owner profile above has a client_id, ALL operations
   belong to that account. Prefix replies: "You are now managing {{business_name}} (Client #{{client_id}})".
3. List accounts: reply with a plain numbered bullet list (name, client_id, vertical, plan).
4. Updates/deactivation emit ONLY the JSON block:
   {{"action": "update_account", "client_id": N, "updates": {{...}}}}
   {{"action": "deactivate_account", "client_id": N}}
5. Never expose another client's whatsapp_number or private data. If a requested
   client_id is not the one in the profile above, refuse politely.
6. Keep text replies <= 180 characters (WhatsApp-friendly). Emojis only when
   brand_voice is casual/playful.
7. When an image is required, return ONLY:
   {{"action": "send_media", "type": "image", "url": "<allowlisted url>", "caption": "<short>"}}
8. If any required field is missing, ask for it instead of guessing."""


# ── Action execution (tenant-safe) ───────────────────────────────────────────
def extract_action(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first {...} JSON action block out of an LLM reply."""
    if not text:
        return None
    m = re.search(r"\{[^{}]*\"action\"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) and data.get("action") else None
    except json.JSONDecodeError:
        return None


def _can_touch(user, client_id: int) -> bool:
    from auth import Role
    try:
        if Role(user.role) == Role.ADMIN:
            return True
    except Exception:
        pass
    return getattr(user, "client_id", None) == int(client_id)


async def execute_account_action(action: Dict[str, Any], user) -> Dict[str, Any]:
    """Validate + execute an LLM-proposed account action, scoped to `user`."""
    from db import async_session, Client
    from auth import Role
    from sqlalchemy import select
    kind = action.get("action")

    if kind == "create_account":
        missing = [f for f in _REQUIRED_FIELDS if not str(action.get(f, "")).strip()]
        if missing:
            return {"ok": False, "error": f"missing required fields: {', '.join(missing)}"}
        async with async_session() as session:
            exists = (await session.execute(
                select(Client).where(
                    Client.whatsapp_number == str(action["whatsapp_number"]).strip())
            )).scalar_one_or_none()
            if exists:
                return {"ok": False, "error": "whatsapp_number already registered"}
            client = Client(
                business_name=str(action["business_name"]).strip()[:255],
                vertical=str(action.get("vertical", "general")).strip().lower()[:20],
                whatsapp_number=str(action["whatsapp_number"]).strip()[:20],
                plan=str(action.get("plan", "trial"))[:20],
            )
            client.business_profile = {
                "brand_voice": str(action.get("brand_voice")
                                   or SUGGESTED_VOICE.get(client.vertical, "casual")),
                **{k: action[k] for k in _MEDIA_KEYS
                   if action.get(k) and str(action[k]).startswith("https://")},
            }
            session.add(client)
            await session.commit()
            await session.refresh(client)
            return {"ok": True, "client_id": client.id,
                    "business_name": client.business_name}

    client_id = action.get("client_id")
    if not client_id:
        return {"ok": False, "error": "client_id required"}
    if not _can_touch(user, int(client_id)):
        return {"ok": False, "error": "not your account (or unknown client_id)"}

    async with async_session() as session:
        client = await session.get(Client, int(client_id))
        if not client:
            return {"ok": False, "error": "client not found"}

        if kind == "update_account":
            updates = action.get("updates") or {}
            applied = {}
            for k, v in updates.items():
                if k not in _UPDATABLE_KEYS:
                    continue
                if k in _MEDIA_KEYS and not str(v).startswith("https://"):
                    continue
                if k == "brand_voice":
                    bp = dict(client.business_profile or {})
                    bp["brand_voice"] = str(v)[:40]
                    client.business_profile = bp
                elif k in _MEDIA_KEYS:
                    bp = dict(client.business_profile or {})
                    bp[k] = str(v)[:500]
                    client.business_profile = bp
                elif k == "business_hours":
                    bp = dict(client.business_profile or {})
                    bp["business_hours"] = str(v)[:120]
                    client.business_profile = bp
                elif k == "custom_fields" and isinstance(v, dict):
                    bp = dict(client.business_profile or {})
                    bp.update({str(kk): str(vv)[:500]
                               for kk, vv in list(v.items())[:20]})
                    client.business_profile = bp
                elif hasattr(client, k):
                    setattr(client, k, str(v)[:255])
                applied[k] = True
            await session.commit()
            return {"ok": True, "client_id": client.id, "updated": applied}

        if kind == "deactivate_account":
            client.is_active = False
            await session.commit()
            return {"ok": True, "client_id": client.id, "is_active": False}

        if kind == "delete_account":
            if Role(user.role) != Role.ADMIN:
                return {"ok": False, "error": "deletion is admin-only; use deactivate"}
            await session.delete(client)
            await session.commit()
            return {"ok": True, "client_id": int(client_id), "deleted": True}

    return {"ok": False, "error": f"unsupported action: {kind!r}"}


async def list_accounts(user) -> Dict[str, Any]:
    """Accounts visible to this user: admins see all, others only their own."""
    from db import async_session, Client
    from auth import Role
    from sqlalchemy import select
    try:
        is_admin = Role(user.role) == Role.ADMIN
    except Exception:
        is_admin = False
    async with async_session() as session:
        q = select(Client).order_by(Client.id)
        if not is_admin:
            q = q.where(Client.id == (user.client_id or -1))
        rows = (await session.execute(q)).scalars().all()
    return {"accounts": [
        {"client_id": c.id, "business_name": c.business_name,
         "vertical": c.vertical, "plan": c.plan, "is_active": bool(c.is_active)}
        for c in rows if is_admin or c.is_active
    ]}


async def call_account_llm(system_prompt: str, user_message: str) -> str:
    """LLM call with a hard timeout; returns raw text."""
    from llm_setup import get_llm
    llm = get_llm()
    resp = await asyncio.wait_for(llm.ainvoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]), timeout=_CREATE_TIMEOUT)
    return resp.content if hasattr(resp, "content") else str(resp)