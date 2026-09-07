"""
Broadcast-Assistant-AI — WhatsApp sales-copywriter for broadcast campaigns.

Generates short, persuasive, brand-voice-matched broadcast copy:

* <= 160 characters (single WhatsApp segment; longer texts are never sent)
* value proposition phrased around the recipient's benefit
* exactly ONE call-to-action (cta_text, optionally cta_link)
* optional single image, ONLY from the owner-provided https image_url
* personalised with the recipient's first name (or "friend"); never mentions
  any other contact

The generated text keeps the platform's {{name}} placeholder support so the
existing BroadcastEngine._personalize_message can substitute per recipient.
If the LLM fails, times out, or returns >160 chars, a deterministic fallback
template built from the owner profile is used instead.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("broadcast_assistant")

MAX_LEN = 160
_LLM_TIMEOUT = 15

_MEDIA_KEY = "image_url"


def build_broadcast_prompt(owner_profile: Dict[str, Any],
                           contact: Dict[str, Any]) -> str:
    """System prompt for the Broadcast-Assistant copywriter."""
    name = (contact.get("name") or "").strip()
    segment = (contact.get("tags") or {}).get("segment", "") \
        if isinstance(contact.get("tags"), dict) else ""
    image_url = owner_profile.get(_MEDIA_KEY) or ""
    valid_image = str(image_url).startswith("https://")

    return f"""You are Broadcast-Assistant-AI, a WhatsApp sales copywriter for a broadcast to ONE contact.

Owner profile (JSON):
{owner_profile}

Recipient (JSON):
{{"name": {name!r}, "segment": {segment!r}}}

Rules for the message you write:
1. MAXIMUM {MAX_LEN} characters (one WhatsApp segment). Count carefully.
2. Match the owner's brand_voice exactly ({owner_profile.get('brand_voice', 'casual')}).
   Emojis only if the voice is casual or playful.
3. Include a clear value proposition: how the owner's service
   ({owner_profile.get('service_summary', '')}) helps THIS recipient.
4. End with exactly ONE easy call-to-action: {owner_profile.get('cta_text', 'Reply YES to know more')}
   {('- include the link: ' + str(owner_profile.get('cta_link'))) if owner_profile.get('cta_link') else ''}
5. Personalise ONLY with the recipient's first name (use "{{{{name}}}}" as the
   placeholder if you reference it; use "friend" when no name). NEVER mention
   any other contact or any data about other customers.
6. If segment is "{segment}", tailor the hook to that audience.

{"A single image will be attached separately: do not describe it in the text." if valid_image else "No image is attached; do not reference any picture."}

Respond with ONLY this JSON, nothing else:
{{"text": "<the broadcast message, <= {MAX_LEN} chars>"}}"""


def _fallback_copy(owner_profile: Dict[str, Any],
                   contact: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic on-brand copy when the LLM is unavailable or too long."""
    name = (contact.get("name") or "").strip()
    first = name or "{{name}}"
    voice = (owner_profile.get("brand_voice") or "casual").lower()
    hi = "Hey" if voice in ("casual", "playful") else "Hello"
    service = owner_profile.get("service_summary") or "our new service"
    cta = owner_profile.get("cta_text") or "Reply YES to know more"
    link = owner_profile.get("cta_link") or ""
    text = f"{hi} {first}! {service}. {cta}" + (f" {link}" if link else "")
    return {"text": text[:MAX_LEN], "image_url": _image_url(owner_profile)}


def _image_url(owner_profile: Dict[str, Any]) -> Optional[str]:
    url = owner_profile.get(_MEDIA_KEY)
    return str(url) if url and str(url).startswith("https://") else None


async def generate_broadcast_copy(owner_profile: Dict[str, Any],
                                  contact: Dict[str, Any]) -> Dict[str, Any]:
    """Generate one broadcast message. Never raises; falls back on any error.

    Returns {"text": str (<=160 chars), "image_url": Optional[str],
             "source": "ai" | "fallback"}.
    """
    try:
        from llm_setup import get_llm
        llm = get_llm()
        resp = await asyncio.wait_for(llm.ainvoke([
            {"role": "system", "content": build_broadcast_prompt(owner_profile, contact)},
            {"role": "user", "content": "Write the broadcast message now."},
        ]), timeout=_LLM_TIMEOUT)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        import json
        import re
        m = re.search(r"\{.*\}", raw, re.S)
        text = ""
        if m:
            try:
                text = str(json.loads(m.group(0)).get("text", ""))
            except json.JSONDecodeError:
                text = raw.strip()
        text = text.strip().strip('"')
        if text and len(text) <= MAX_LEN:
            return {"text": text, "image_url": _image_url(owner_profile),
                    "source": "ai"}
        logger.warning("[!] broadcast copy %d chars (limit %d); using fallback",
                       len(text), MAX_LEN)
    except Exception as e:
        logger.warning("[!] broadcast copy LLM failed (%s); using fallback", e)
    out = _fallback_copy(owner_profile, contact)
    out["source"] = "fallback"
    return out