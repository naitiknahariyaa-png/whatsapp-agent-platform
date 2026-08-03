"""
Multi-Channel Hub — Unified inbox for Instagram, Telegram, SMS, Email, WhatsApp
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Any, List, Callable, Awaitable
from datetime import datetime
from enum import Enum

logger = logging.getLogger("multi_channel_hub")


class ChannelType(Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    SMS = "sms"
    EMAIL = "email"
    WEB_CHAT = "web_chat"


class MessageDirection(Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class UnifiedMessage:
    """Normalized message across all channels"""

    def __init__(self, channel: ChannelType, contact_id: str, content: str,
                 direction: MessageDirection = MessageDirection.INCOMING,
                 media_url: Optional[str] = None,
                 metadata: Optional[Dict] = None):
        self.channel = channel
        self.contact_id = contact_id
        self.content = content
        self.direction = direction
        self.media_url = media_url
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat()
        self.message_id = f"{channel.value}_{contact_id}_{int(datetime.utcnow().timestamp())}"

    def to_dict(self) -> Dict:
        return {
            "message_id": self.message_id,
            "channel": self.channel.value,
            "contact_id": self.contact_id,
            "content": self.content,
            "direction": self.direction.value,
            "media_url": self.media_url,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }


class ChannelAdapter:
    """Base class for channel adapters"""

    def __init__(self, config: Dict):
        self.config = config
        self.name = "base"

    async def send_message(self, message: UnifiedMessage) -> bool:
        raise NotImplementedError

    async def receive_messages(self) -> List[UnifiedMessage]:
        raise NotImplementedError

    async def health_check(self) -> bool:
        raise NotImplementedError


class InstagramAdapter(ChannelAdapter):
    """Instagram DM via Meta Graph API"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.name = "instagram"
        self.access_token = config.get("instagram_access_token", "")
        self.ig_user_id = config.get("instagram_user_id", "")

    async def send_message(self, message: UnifiedMessage) -> bool:
        try:
            import httpx
            url = f"https://graph.facebook.com/v18.0/{self.ig_user_id}/messages"
            payload = {
                "recipient": {"id": message.contact_id},
                "message": {"text": message.content},
                "access_token": self.access_token,
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Instagram send failed: {e}")
            return False

    async def receive_messages(self) -> List[UnifiedMessage]:
        # Webhook-based; this is a placeholder for polling fallback
        return []

    async def health_check(self) -> bool:
        return bool(self.access_token and self.ig_user_id)


class TelegramAdapter(ChannelAdapter):
    """Telegram Bot API"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.name = "telegram"
        self.bot_token = config.get("telegram_bot_token", "")
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"

    async def send_message(self, message: UnifiedMessage) -> bool:
        try:
            import httpx
            url = f"{self.api_base}/sendMessage"
            payload = {
                "chat_id": message.contact_id,
                "text": message.content,
                "parse_mode": "HTML",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def receive_messages(self) -> List[UnifiedMessage]:
        try:
            import httpx
            url = f"{self.api_base}/getUpdates"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params={"timeout": 30})
                if resp.status_code == 200:
                    updates = resp.json().get("result", [])
                    messages = []
                    for update in updates:
                        msg = update.get("message", {})
                        if msg.get("text"):
                            messages.append(UnifiedMessage(
                                channel=ChannelType.TELEGRAM,
                                contact_id=str(msg["from"]["id"]),
                                content=msg["text"],
                                metadata={"update_id": update["update_id"]},
                            ))
                    return messages
        except Exception as e:
            logger.error(f"Telegram receive failed: {e}")
        return []

    async def health_check(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.api_base}/getMe")
                return resp.status_code == 200
        except Exception:
            return False


class SMSAdapter(ChannelAdapter):
    """Twilio SMS"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.name = "sms"
        self.account_sid = config.get("twilio_account_sid", "")
        self.auth_token = config.get("twilio_auth_token", "")
        self.from_number = config.get("twilio_from_number", "")

    async def send_message(self, message: UnifiedMessage) -> bool:
        try:
            from twilio.rest import Client
            client = Client(self.account_sid, self.auth_token)
            twilio_msg = client.messages.create(
                body=message.content,
                from_=self.from_number,
                to=message.contact_id,
            )
            return twilio_msg.sid is not None
        except Exception as e:
            logger.error(f"SMS send failed: {e}")
            return False

    async def receive_messages(self) -> List[UnifiedMessage]:
        # Webhook-based via Twilio status callback
        return []

    async def health_check(self) -> bool:
        return bool(self.account_sid and self.auth_token)


class EmailAdapter(ChannelAdapter):
    """SendGrid / Resend Email"""

    def __init__(self, config: Dict):
        super().__init__(config)
        self.name = "email"
        self.api_key = config.get("email_api_key", "")
        self.from_email = config.get("from_email", "")
        self.provider = config.get("email_provider", "sendgrid")  # sendgrid | resend

    async def send_message(self, message: UnifiedMessage) -> bool:
        try:
            import httpx
            if self.provider == "sendgrid":
                url = "https://api.sendgrid.com/v3/mail/send"
                payload = {
                    "personalizations": [{"to": [{"email": message.contact_id}]}],
                    "from": {"email": self.from_email},
                    "subject": message.metadata.get("subject", "Message from WhatsApp Agent"),
                    "content": [{"type": "text/plain", "value": message.content}],
                }
                headers = {"Authorization": f"Bearer {self.api_key}"}
            else:  # resend
                url = "https://api.resend.com/emails"
                payload = {
                    "from": self.from_email,
                    "to": [message.contact_id],
                    "subject": message.metadata.get("subject", "Message from WhatsApp Agent"),
                    "text": message.content,
                }
                headers = {"Authorization": f"Bearer {self.api_key}"}

            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers)
                return resp.status_code in (200, 201, 202)
        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return False

    async def receive_messages(self) -> List[UnifiedMessage]:
        # Webhook-based via SendGrid Inbound Parse / Resend webhooks
        return []

    async def health_check(self) -> bool:
        return bool(self.api_key and self.from_email)


class MultiChannelHub:
    """
    Unified hub that routes messages across all channels.
    Provides a single API for the agent to send/receive regardless of channel.
    """

    def __init__(self):
        self.adapters: Dict[ChannelType, ChannelAdapter] = {}
        self.message_handlers: List[Callable[[UnifiedMessage], Awaitable[None]]] = []
        self._running = False
        self._poll_task = None

    def register_adapter(self, channel: ChannelType, adapter: ChannelAdapter):
        """Register a channel adapter"""
        self.adapters[channel] = adapter
        logger.info(f"[+] Registered adapter: {channel.value}")

    def register_handler(self, handler: Callable[[UnifiedMessage], Awaitable[None]]):
        """Register a handler for incoming messages"""
        self.message_handlers.append(handler)

    async def send(self, channel: ChannelType, contact_id: str, content: str,
                   media_url: Optional[str] = None, metadata: Optional[Dict] = None) -> bool:
        """Send a message through a specific channel"""
        adapter = self.adapters.get(channel)
        if not adapter:
            logger.error(f"No adapter for channel: {channel.value}")
            return False

        message = UnifiedMessage(
            channel=channel,
            contact_id=contact_id,
            content=content,
            direction=MessageDirection.OUTGOING,
            media_url=media_url,
            metadata=metadata,
        )
        return await adapter.send_message(message)

    async def broadcast(self, channel: ChannelType, contact_ids: List[str],
                        content: str, metadata: Optional[Dict] = None) -> Dict[str, bool]:
        """Send same message to multiple contacts on a channel"""
        results = {}
        for cid in contact_ids:
            results[cid] = await self.send(channel, cid, content, metadata=metadata)
            await asyncio.sleep(0.05)  # rate limit buffer
        return results

    async def _handle_incoming(self, message: UnifiedMessage):
        """Route incoming message to all registered handlers"""
        for handler in self.message_handlers:
            try:
                await handler(message)
            except Exception as e:
                logger.error(f"Handler error: {e}")

    async def start_polling(self, interval: float = 5.0):
        """Start polling all channels for incoming messages"""
        self._running = True

        async def _poll():
            while self._running:
                for channel, adapter in self.adapters.items():
                    try:
                        messages = await adapter.receive_messages()
                        for msg in messages:
                            await self._handle_incoming(msg)
                    except Exception as e:
                        logger.debug(f"Poll error for {channel.value}: {e}")
                await asyncio.sleep(interval)

        self._poll_task = asyncio.create_task(_poll())
        logger.info("[v] Multi-channel polling started")

    async def stop_polling(self):
        """Stop polling"""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

    async def health(self) -> Dict[str, bool]:
        """Get health status of all channels"""
        status = {}
        for channel, adapter in self.adapters.items():
            try:
                status[channel.value] = await adapter.health_check()
            except Exception:
                status[channel.value] = False
        return status


# Global hub instance
hub = MultiChannelHub()