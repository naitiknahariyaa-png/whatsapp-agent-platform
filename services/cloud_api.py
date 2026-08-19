"""
WhatsApp Cloud API Integration — Official Meta WhatsApp Business Platform API
Provides:
- Token-based connection (no QR scanning after initial setup)
- Phone number ID management
- Message sending via templates and free-text (within policy limits)
- Webhook verification and event handling
- Rate limiting and tier management
"""
import os
import json
import logging
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, field

import httpx

from config import settings

logger = logging.getLogger("cloud_api")

# Meta WhatsApp Cloud API defaults
META_API_VERSION = "v18.0"
META_GRAPH_URL = f"https://graph.facebook.com/{META_API_VERSION}"


@dataclass
class CloudAPIConfig:
    """WhatsApp Cloud API configuration for a business"""
    client_id: int
    access_token: str
    phone_number_id: str
    business_account_id: Optional[str] = None
    app_id: Optional[str] = None
    webhook_verify_token: Optional[str] = None
    is_active: bool = True
    tier: str = "tier_1"  # tier_1: 250, tier_2: 1k, tier_3: 10k, tier_4: 100k+ unique recipients/day
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class WhatsAppCloudAPI:
    """Official Meta WhatsApp Business Cloud API client"""

    def __init__(self):
        self.configs: Dict[int, CloudAPIConfig] = {}
        self._load_configs()

    def _load_configs(self):
        """Load Cloud API configs from disk"""
        try:
            config_dir = os.path.join(os.path.dirname(__file__), "..", "agent-engine", "data", "cloud_api")
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, "configs.json")
            if os.path.exists(config_file):
                with open(config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for c in data.get("configs", []):
                        config = CloudAPIConfig(
                            client_id=c["client_id"],
                            access_token=c["access_token"],
                            phone_number_id=c["phone_number_id"],
                            business_account_id=c.get("business_account_id"),
                            app_id=c.get("app_id"),
                            webhook_verify_token=c.get("webhook_verify_token"),
                            is_active=c.get("is_active", True),
                            tier=c.get("tier", "tier_1"),
                            created_at=c.get("created_at", datetime.utcnow().isoformat()),
                            updated_at=c.get("updated_at", datetime.utcnow().isoformat()),
                        )
                        self.configs[config.client_id] = config
        except Exception as e:
            logger.warning(f"Failed to load Cloud API configs: {e}")

    def _save_configs(self):
        """Save Cloud API configs to disk"""
        try:
            config_dir = os.path.join(os.path.dirname(__file__), "..", "agent-engine", "data", "cloud_api")
            os.makedirs(config_dir, exist_ok=True)
            config_file = os.path.join(config_dir, "configs.json")
            data = {
                "configs": [
                    {
                        "client_id": c.client_id,
                        "access_token": c.access_token,
                        "phone_number_id": c.phone_number_id,
                        "business_account_id": c.business_account_id,
                        "app_id": c.app_id,
                        "webhook_verify_token": c.webhook_verify_token,
                        "is_active": c.is_active,
                        "tier": c.tier,
                        "created_at": c.created_at,
                        "updated_at": c.updated_at,
                    }
                    for c in self.configs.values()
                ]
            }
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save Cloud API configs: {e}")

    def register_client(self, client_id: int, access_token: str, phone_number_id: str,
                        business_account_id: Optional[str] = None, app_id: Optional[str] = None,
                        webhook_verify_token: Optional[str] = None) -> CloudAPIConfig:
        """Register a client's WhatsApp Business Cloud API credentials"""
        config = CloudAPIConfig(
            client_id=client_id,
            access_token=access_token,
            phone_number_id=phone_number_id,
            business_account_id=business_account_id,
            app_id=app_id,
            webhook_verify_token=webhook_verify_token,
        )
        self.configs[client_id] = config
        self._save_configs()
        return config

    def get_config(self, client_id: int) -> Optional[CloudAPIConfig]:
        """Get Cloud API config for a client"""
        return self.configs.get(client_id)

    def remove_config(self, client_id: int) -> bool:
        """Remove Cloud API config for a client"""
        if client_id in self.configs:
            del self.configs[client_id]
            self._save_configs()
            return True
        return False

    def verify_token(self, client_id: int, token: str) -> bool:
        """Verify access token is valid by calling Meta API"""
        config = self.configs.get(client_id)
        if not config:
            return False
        try:
            resp = httpx.get(
                f"{META_GRAPH_URL}/{config.phone_number_id}",
                params={"access_token": config.access_token},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Token verification failed: {e}")
            return False

    def send_template_message(self, client_id: int, to_number: str, template_name: str,
                              language: str = "en", components: List[Dict] = None) -> Dict[str, Any]:
        """Send a pre-approved template message via Cloud API"""
        config = self.configs.get(client_id)
        if not config:
            return {"status": "error", "message": "Cloud API not configured for this client"}

        url = f"{META_GRAPH_URL}/{config.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        if components:
            payload["template"]["components"] = components

        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                wamid = data.get("messages", [{}])[0].get("id", "")
                return {"status": "sent", "wamid": wamid, "response": data}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_free_text(self, client_id: int, to_number: str, message: str,
                       reply_to_message_id: Optional[str] = None) -> Dict[str, Any]:
        """Send a free-form text message (only within 24-hour session window)"""
        config = self.configs.get(client_id)
        if not config:
            return {"status": "error", "message": "Cloud API not configured for this client"}

        url = f"{META_GRAPH_URL}/{config.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message},
        }
        if reply_to_message_id:
            payload["context"] = {"message_id": reply_to_message_id}

        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                wamid = data.get("messages", [{}])[0].get("id", "")
                return {"status": "sent", "wamid": wamid, "response": data}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def send_image(self, client_id: int, to_number: str, image_url: str,
                   caption: Optional[str] = None) -> Dict[str, Any]:
        """Send an image with optional caption via Cloud API (within 24h session window)."""
        config = self.configs.get(client_id)
        if not config:
            return {"status": "error", "message": "Cloud API not configured for this client"}

        url = f"{META_GRAPH_URL}/{config.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption

        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                wamid = data.get("messages", [{}])[0].get("id", "")
                return {"status": "sent", "wamid": wamid, "response": data}
            return {"status": "error", "code": resp.status_code, "message": resp.text}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_tier_limits(self, client_id: int) -> Dict[str, Any]:
        """Get messaging tier limits for a client"""
        config = self.configs.get(client_id)
        if not config:
            return {"tier": "unknown", "daily_limit": 0}
        tier_limits = {
            "tier_1": 250,
            "tier_2": 1000,
            "tier_3": 10000,
            "tier_4": 100000,
        }
        return {
            "tier": config.tier,
            "daily_limit": tier_limits.get(config.tier, 250),
            "phone_number_id": config.phone_number_id,
        }

    def get_quality_rating(self, client_id: int) -> Dict[str, Any]:
        """Get phone number quality rating from Meta"""
        config = self.configs.get(client_id)
        if not config:
            return {"error": "Not configured"}
        try:
            resp = httpx.get(
                f"{META_GRAPH_URL}/{config.phone_number_id}",
                params={"access_token": config.access_token, "fields": "quality_rating"},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": resp.text}
        except Exception as e:
            return {"error": str(e)}


cloud_api = WhatsAppCloudAPI()
