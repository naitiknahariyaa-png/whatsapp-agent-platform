"""
Telegram Bot Bridge — lightweight async polling client.
Bridges Telegram chats to the FastAPI agent backend.
Uses standard HTTP/JSON requests with no extra library dependencies.
"""
import asyncio
import sys
import httpx
from dotenv import load_dotenv

load_dotenv()
from config import settings


TELEGRAM_API_BASE = "https://api.telegram.org/bot"
AGENT_API_URL = f"http://localhost:{settings.port}"


async def get_bot_details(client: httpx.AsyncClient, token: str) -> dict:
    url = f"{TELEGRAM_API_BASE}{token}/getMe"
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()["result"]


async def send_message(client: httpx.AsyncClient, token: str, chat_id: int, text: str):
    url = f"{TELEGRAM_API_BASE}{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        resp = await client.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"[!] Failed to send message to {chat_id}: {resp.text}")
    except Exception as e:
        print(f"[!] Error sending message to {chat_id}: {e}")


async def process_telegram_update(client: httpx.AsyncClient, token: str, update: dict):
    message = update.get("message")
    if not message or "text" not in message:
        return
    
    chat_id = message["chat"]["id"]
    user_text = message["text"]
    user_name = message["chat"].get("first_name", "Telegram User")
    
    print(f"[TG IN] {chat_id} ({user_name}): {user_text[:80]}")
    
    # Prefix chat_id with "tg_" to store as phone number in SQLite
    phone_number = f"tg_{chat_id}"
    
    try:
        # Route to FastAPI backend
        resp = await client.post(
            f"{AGENT_API_URL}/api/message",
            json={"phone_number": phone_number, "message": user_text},
            timeout=30
        )
        if resp.status_code == 200:
            reply = resp.json().get("reply", "")
            if reply:
                await send_message(client, token, chat_id, reply)
                print(f"[TG OUT] {chat_id}: {reply[:50]}...")
        else:
            print(f"[!] FastAPI returned error: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"[!] Error contacting FastAPI server: {e}")


async def main():
    token = settings.telegram_bot_token
    if not token or token == "your_telegram_bot_token_here":
        print("[!] TELEGRAM_BOT_TOKEN not configured in .env!")
        print("[ℹ] Get a token from @BotFather on Telegram and update your .env file.")
        sys.exit(1)

    print("[ℹ] Starting Telegram Bot Bridge...")
    
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            bot_info = await get_bot_details(client, token)
            print(f"[✓] Telegram bot verified: @{bot_info['username']} ({bot_info['first_name']})")
        except Exception as e:
            print(f"[✗] Failed to verify Telegram token: {e}")
            sys.exit(1)
        
        offset = 0
        print("[v] Polling for Telegram messages... (Press Ctrl+C to stop)")
        
        while True:
            try:
                url = f"{TELEGRAM_API_BASE}{token}/getUpdates"
                params = {"offset": offset, "timeout": 10}
                
                resp = await client.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    for update in updates:
                        # Process update
                        await process_telegram_update(client, token, update)
                        # Advance offset
                        offset = update["update_id"] + 1
                elif resp.status_code == 409:
                    print("[!] Webhook conflict. If you set a webhook, delete it first: api.telegram.org/bot<token>/deleteWebhook")
                    await asyncio.sleep(5)
                else:
                    print(f"[!] Polling failed: {resp.status_code} - {resp.text}")
                    await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[!] Connection error during polling: {e}")
                await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[ℹ] Telegram bot stopped.")
