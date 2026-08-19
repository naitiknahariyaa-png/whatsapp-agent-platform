"""
Human handoff system - escalate to Telegram when AI confidence is low
"""
import os
import httpx
from datetime import datetime
from typing import Optional
from sqlalchemy import text as sql_text
from db import get_session


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")


async def request_handoff(phone_number: str, reason: str, confidence: float):
    """Mark conversation for human takeover and notify Telegram"""
    async for session in get_session():
        await session.execute(
            sql_text("UPDATE conversations SET status = 'human_takeover' WHERE phone_number = :pn"),
            {"pn": phone_number}
        )
        await session.commit()
    
    # Send Telegram alert
    message = f"🔴 Handoff Request\nPhone: {phone_number}\nReason: {reason}\nConfidence: {confidence:.2f}"
    await send_telegram_message(message, phone_number)


async def send_telegram_message(text: str, phone_number: str = ""):
    """Send message to Telegram admin"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={
            "chat_id": TELEGRAM_ADMIN_CHAT_ID,
            "text": text,
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Take Over", "callback_data": f"takeover:{phone_number}"}
                ]]
            }
        })


async def send_push_notification(title: str, body: str, phone_number: str = ""):
    """Send push notification via Telegram for hot leads and alerts."""
    await send_telegram_message(f"🔔 {title}\n{body}", phone_number)


async def send_whatsapp_message(phone_number: str, text: str):
    """Send message to WhatsApp via bridge"""
    async with httpx.AsyncClient() as client:
        try:
            await client.post("http://localhost:3001/send", json={
                "to": phone_number,
                "message": text
            }, timeout=5.0)
        except httpx.ConnectError:
            pass  # Bridge not running


async def handle_telegram_webhook(update: dict):
    """Handle Telegram admin replies"""
    if "message" in update and "reply_to_message" in update.get("message", {}):
        text = update["message"]["text"]
        phone_number = extract_phone_from_context(update)
        
        if phone_number:
            await send_whatsapp_message(phone_number, text)


def extract_phone_from_context(update: dict) -> Optional[str]:
    """Extract phone number from Telegram callback data or message context"""
    if "callback_query" in update:
        data = update["callback_query"].get("data", "")
        if data.startswith("takeover:"):
            return data.split("takeover:")[1]
    return None