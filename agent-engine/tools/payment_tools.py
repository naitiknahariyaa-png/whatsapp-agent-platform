import logging
import uuid
import httpx
from typing import Dict, Any, Optional
from tools.dispatcher import tool_dispatcher
from db import async_session, Contact

logger = logging.getLogger(\"payment_tools\")

class PaymentProvider:
    \"\"\"Interface for payment gateways (Razorpay/Stripe).\"\"\"
    def __init__(self, provider=\"razorpay\"):
        self.provider = provider
        self.api_key = \"sk_test_mock\" # Should come from .env

    async def create_payment_link(self, amount: float, currency: str, customer_id: str) -> str:
        \"\"\"Generates a payment link. In production, this calls the API.\"\"\"
        # Mock API call
        payment_id = f\"pay_{uuid.uuid4().hex[:10]}\"
        return f\"https://{self.provider}.com/pay/{payment_id}?amount={amount}&curr={currency}\"

payment_provider = PaymentProvider()

async def generate_payment_link(phone_number: str, amount: float, currency: str = \"INR\"):
    \"\"\"
    Tool to generate a payment link for a customer.
    \"\"\"
    try:
        link = await payment_provider.create_payment_link(amount, currency, phone_number)
        return {\"status\": \"success\", \"payment_link\": link, \"amount\": amount}
    except Exception as e:
        return {\"status\": \"error\", \"message\": str(e)}

async def handle_payment_webhook(payload: Dict[str, Any]):
    \"\"\"
    Webhook listener: Auto-updates lead status upon payment confirmation.
    This is called by the FastAPI endpoint.
    \"\"\"
    phone_number = payload.get(\"customer_phone\")
    payment_status = payload.get(\"status\")
    
    if not phone_number or payment_status != \"captured\":
        return {\"status\": \"ignored\"}

    async with async_session() as session:
        from db import Contact
        from sqlalchemy import select
        result = await session.execute(select(Contact).where(Contact.phone_number == phone_number))
        contact = result.scalar_one_or_none()
        if contact:
            contact.lead_status = \"converted\"
            # Update lead score for paying customers
            contact.lead_score += 100
            await session.commit()
            return {\"status\": \"success\", \"message\": f\"Lead {phone_number} marked as converted\"}
    
    return {\"status\": \"error\", \"message\": \"Contact not found\"}

tool_dispatcher.register(\"generate_payment_link\", generate_payment_link)
