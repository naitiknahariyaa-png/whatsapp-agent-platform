"""
Phase 5: Public REST API — API key management, rate limiting, webhooks, SDK support
"""
import json
import logging
import secrets
import hashlib
import hmac
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger("public_api")


class APIKeyPermission(Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    WEBHOOK = "webhook"


@dataclass
class APIKey:
    """An API key for external access"""
    key_id: str
    key_hash: str
    name: str
    client_id: int
    permissions: List[APIKeyPermission]
    allowed_ips: List[str] = field(default_factory=list)
    rate_limit_per_minute: int = 60
    is_active: bool = True
    expires_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_used_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "key_id": self.key_id,
            "name": self.name,
            "client_id": self.client_id,
            "permissions": [p.value for p in self.permissions],
            "allowed_ips": self.allowed_ips,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "is_active": self.is_active,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }


class APIKeyManager:
    """Manage API keys for external developers"""

    def __init__(self):
        self.keys: Dict[str, APIKey] = {}  # key_id -> APIKey
        self._rate_limit_buckets: Dict[str, List[datetime]] = {}

    def create_key(self, name: str, client_id: int,
                   permissions: Optional[List[APIKeyPermission]] = None,
                   rate_limit: int = 60) -> Dict:
        """Create a new API key. Returns the key (only shown once)."""
        key_id = f"wap_{secrets.token_hex(8)}"
        raw_key = f"sk_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            name=name,
            client_id=client_id,
            permissions=permissions or [APIKeyPermission.READ, APIKeyPermission.WRITE],
            rate_limit_per_minute=rate_limit,
        )
        self.keys[key_id] = api_key
        logger.info(f"[+] API key created: {key_id} for client {client_id}")

        return {
            "key_id": key_id,
            "api_key": raw_key,  # Only shown once!
            "permissions": [p.value for p in api_key.permissions],
        }

    def validate(self, api_key: str) -> Optional[APIKey]:
        """Validate an API key and return the key object"""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        for key in self.keys.values():
            if key.key_hash == key_hash and key.is_active:
                # Check expiry
                if key.expires_at:
                    expires = datetime.fromisoformat(key.expires_at)
                    if datetime.utcnow() > expires:
                        continue
                key.last_used_at = datetime.utcnow().isoformat()
                return key
        return None

    def check_rate_limit(self, api_key: str) -> bool:
        """Check if request is within rate limit"""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        now = datetime.utcnow()

        if key_hash not in self._rate_limit_buckets:
            self._rate_limit_buckets[key_hash] = []

        bucket = self._rate_limit_buckets[key_hash]
        # Remove requests older than 1 minute
        bucket[:] = [t for t in bucket if (now - t).total_seconds() < 60]

        # Find the key to get its limit
        for key in self.keys.values():
            if key.key_hash == key_hash:
                if len(bucket) >= key.rate_limit_per_minute:
                    return False
                break

        bucket.append(now)
        return True

    def revoke(self, key_id: str) -> bool:
        """Revoke an API key"""
        key = self.keys.get(key_id)
        if key:
            key.is_active = False
            logger.info(f"[-] API key revoked: {key_id}")
            return True
        return False

    def list_keys(self, client_id: int) -> List[Dict]:
        """List all keys for a client"""
        return [
            k.to_dict() for k in self.keys.values()
            if k.client_id == client_id
        ]


# ---------------------------------------------------------------------------
# Webhooks System
# ---------------------------------------------------------------------------

class WebhookEvent(Enum):
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    LEAD_CREATED = "lead.created"
    LEAD_UPDATED = "lead.updated"
    APPOINTMENT_BOOKED = "appointment.booked"
    APPOINTMENT_CANCELLED = "appointment.cancelled"
    PAYMENT_RECEIVED = "payment.received"
    HUMAN_HANDOFF = "human.handoff"
    CAMPAIGN_COMPLETED = "campaign.completed"
    ERROR = "error"


@dataclass
class WebhookEndpoint:
    """A registered webhook endpoint"""
    id: str
    client_id: int
    url: str
    events: List[WebhookEvent]
    secret: str
    is_active: bool = True
    retry_count: int = 3
    timeout_seconds: int = 10
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "url": self.url,
            "events": [e.value for e in self.events],
            "is_active": self.is_active,
            "retry_count": self.retry_count,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
        }


class WebhookManager:
    """Manage and dispatch webhooks"""

    def __init__(self):
        self.endpoints: Dict[str, WebhookEndpoint] = {}
        self._delivery_log: List[Dict] = []

    def register(self, client_id: int, url: str, events: List[WebhookEvent],
                 secret: Optional[str] = None) -> WebhookEndpoint:
        """Register a webhook endpoint"""
        endpoint_id = f"wh_{secrets.token_hex(8)}"
        endpoint = WebhookEndpoint(
            id=endpoint_id,
            client_id=client_id,
            url=url,
            events=events,
            secret=secret or secrets.token_hex(16),
        )
        self.endpoints[endpoint_id] = endpoint
        logger.info(f"[+] Webhook registered: {endpoint_id} -> {url}")
        return endpoint

    def unregister(self, endpoint_id: str) -> bool:
        """Unregister a webhook endpoint"""
        return bool(self.endpoints.pop(endpoint_id, None))

    def _sign_payload(self, payload: bytes, secret: str) -> str:
        """Sign webhook payload with HMAC-SHA256"""
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    async def dispatch(self, event: WebhookEvent, client_id: int, payload: Dict):
        """Dispatch an event to all matching webhooks"""
        import httpx

        for endpoint in list(self.endpoints.values()):
            if (endpoint.client_id == client_id and
                endpoint.is_active and
                event in endpoint.events):

                body = json.dumps({
                    "event": event.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "payload": payload,
                }, default=str).encode()

                signature = self._sign_payload(body, endpoint.secret)

                for attempt in range(endpoint.retry_count):
                    try:
                        async with httpx.AsyncClient() as client:
                            resp = await client.post(
                                endpoint.url,
                                content=body,
                                headers={
                                    "Content-Type": "application/json",
                                    "X-Webhook-Signature": signature,
                                    "X-Webhook-Event": event.value,
                                },
                                timeout=endpoint.timeout_seconds,
                            )
                        success = resp.status_code < 300
                        self._delivery_log.append({
                            "endpoint_id": endpoint.id,
                            "event": event.value,
                            "attempt": attempt + 1,
                            "success": success,
                            "status_code": resp.status_code,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        if success:
                            break
                    except Exception as e:
                        logger.error(f"Webhook delivery failed (attempt {attempt+1}): {e}")

    def get_delivery_log(self, endpoint_id: Optional[str] = None,
                         limit: int = 50) -> List[Dict]:
        """Get webhook delivery log"""
        logs = self._delivery_log
        if endpoint_id:
            logs = [l for l in logs if l["endpoint_id"] == endpoint_id]
        return logs[-limit:]


# ---------------------------------------------------------------------------
# SDK Support — Auto-generated client code
# ---------------------------------------------------------------------------

class SDKGenerator:
    """Generate SDK code for Node.js, Python, PHP"""

    @staticmethod
    def generate_python_sdk(api_base: str = "https://api.yourapp.com") -> str:
        return f'''"""
WhatsApp Agent Platform — Python SDK
"""
import json
import hashlib
import hmac
from typing import Optional, Dict, List
from datetime import datetime

import httpx


class WAPClient:
    """WhatsApp Agent Platform Python Client"""

    def __init__(self, api_key: str, base_url: str = "{api_base}"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(headers={{"Authorization": f"Bearer {{api_key}}"}})

    def send_message(self, phone_number: str, message: str,
                     client_id: int = 1) -> Dict:
        """Send a message via the AI agent"""
        resp = self._client.post(
            f"{{self.base_url}}/api/message",
            json={{"phone_number": phone_number, "message": message, "client_id": client_id}},
        )
        return resp.json()

    def get_lead(self, contact_id: str, client_id: int = 1) -> Dict:
        """Get lead profile and score"""
        resp = self._client.get(
            f"{{self.base_url}}/api/leads/{{contact_id}}",
            params={{"client_id": client_id}},
        )
        return resp.json()

    def get_conversations(self, phone_number: str, limit: int = 20) -> List[Dict]:
        """Get conversation history"""
        resp = self._client.get(
            f"{{self.base_url}}/api/conversations/{{phone_number}}",
            params={{"limit": limit}},
        )
        return resp.json()

    def health(self) -> Dict:
        """Check API health"""
        resp = self._client.get(f"{{self.base_url}}/health")
        return resp.json()
'''

    @staticmethod
    def generate_node_sdk(api_base: str = "https://api.yourapp.com") -> str:
        return f'''/**
 * WhatsApp Agent Platform — Node.js SDK
 */
import axios from 'axios';

export class WAPClient {{
    private client;

    constructor(
        private apiKey: string,
        private baseUrl: string = '{api_base}'
    ) {{
        this.client = axios.create({{
            baseURL: baseUrl,
            headers: {{ Authorization: `Bearer ${{apiKey}}` }},
        }});
    }}

    async sendMessage(phoneNumber: string, message: string, clientId = 1) {{
        const {{ data }} = await this.client.post('/api/message', {{
            phone_number: phoneNumber,
            message,
            client_id: clientId,
        }});
        return data;
    }}

    async getLead(contactId: string, clientId = 1) {{
        const {{ data }} = await this.client.get(`/api/leads/${{contactId}}`, {{
            params: {{ client_id: clientId }},
        }});
        return data;
    }}

    async getConversations(phoneNumber: string, limit = 20) {{
        const {{ data }} = await this.client.get(`/api/conversations/${{phoneNumber}}`, {{
            params: {{ limit }},
        }});
        return data;
    }}

    async health() {{
        const {{ data }} = await this.client.get('/health');
        return data;
    }}
}}
'''

    @staticmethod
    def generate_php_sdk(api_base: str = "https://api.yourapp.com") -> str:
        return f'''<?php
/**
 * WhatsApp Agent Platform — PHP SDK
 */
class WAPClient {{
    private string $apiKey;
    private string $baseUrl;
    private $client;

    public function __construct(string $apiKey, string $baseUrl = '{api_base}') {{
        $this->apiKey = $apiKey;
        $this->baseUrl = rtrim($baseUrl, '/');
    }}

    private function request(string $method, string $path, array $data = []): array {{
        $ch = curl_init("{{$this->baseUrl}}{{$path}}");
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_setopt($ch, CURLOPT_HTTPHEADER, [
            'Authorization: Bearer {{$this->apiKey}}',
            'Content-Type: application/json',
        ]);
        if ($method === 'POST') {{
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));
        }}
        $response = curl_exec($ch);
        curl_close($ch);
        return json_decode($response, true) ?? [];
    }}

    public function sendMessage(string $phoneNumber, string $message, int $clientId = 1): array {{
        return $this->request('POST', '/api/message', [
            'phone_number' => $phoneNumber,
            'message' => $message,
            'client_id' => $clientId,
        ]);
    }}

    public function health(): array {{
        return $this->request('GET', '/health');
    }}
}}
'''


# Global instances
api_key_manager = APIKeyManager()
webhook_manager = WebhookManager()
sdk_generator = SDKGenerator()