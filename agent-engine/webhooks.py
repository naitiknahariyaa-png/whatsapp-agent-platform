"""
n8n webhook integration - trigger external workflows
"""
import httpx
from typing import Dict, Any
import os

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook")

WEBHOOK_EVENTS = {
    "appointment_confirmed": "/appointment-confirmed",
    "payment_received": "/payment-received",
    "lead_qualified": "/lead-qualified",
    "document_uploaded": "/document-uploaded",
    "handoff_requested": "/handoff-requested"
}


async def trigger_webhook(event_type: str, payload: Dict[str, Any]):
    """Trigger n8n webhook for custom workflow"""
    if event_type not in WEBHOOK_EVENTS:
        return
    
    url = f"{N8N_WEBHOOK_URL}{WEBHOOK_EVENTS[event_type]}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(url, json=payload)
        except httpx.ConnectError:
            pass  # n8n not running, silently fail