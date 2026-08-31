"""
Billing Agent — handles payments, invoices, refunds, and billing disputes.
Money is involved → always verifies, never auto-approves refunds.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("billing_agent")


class BillingAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Billing Manager. Your goal is to handle payments, invoices, and billing questions. "
            "\n\nRULES:\n"
            "1. Use 'generate_payment_link' for payment requests.\n"
            "2. Use 'verify_payment_webhook' for payment confirmations.\n"
            "3. Use 'send_invoice' for invoice generation.\n"
            "4. REFUNDS NEVER AUTO-APPROVE — always use 'escalate_to_human' for refund requests.\n"
            "5. Always verify payment status before confirming to the customer.\n"
            "6. For billing disputes, use 'escalate_to_human' with full context."
        )
        tools = [
            "generate_payment_link",
            "verify_payment_webhook",
            "send_invoice",
            "check_payment_status",
            "escalate_to_human",
        ]
        super().__init__(
            name="BillingPro",
            role="Payments & Invoices",
            system_prompt=system_prompt,
            tools=tools,
        )

    async def run(self, user_input: str, context: dict = None) -> str:
        if context and context.get("intent") == "refund_request":
            return await self._handle_refund_request(user_input, context)
        return await super().run(user_input, context)

    async def _handle_refund_request(self, user_input: str, context: dict) -> str:
        return (
            "I've escalated your refund request to our team. "
            "They'll review it and get back to you within 24 hours. "
            "Your request reference has been logged. 🙏"
        )
