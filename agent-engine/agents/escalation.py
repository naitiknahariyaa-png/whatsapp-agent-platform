"""
Escalation Agent — safety net for all other workers.
Handles human handoff, context packaging, and owner notification.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("escalation_agent")


class EscalationAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Escalation Specialist. Your goal is to smoothly transition complex or emotional "
            "customer interactions to a human agent. "
            "\n\nRULES:\n"
            "1. Use 'escalate_to_human' to initiate a handoff.\n"
            "2. Use 'notify_owner' to alert the business owner.\n"
            "3. Use 'package_context_for_human' to prepare conversation summary.\n"
            "4. Always acknowledge the customer's frustration or concern before escalating.\n"
            "5. Set clear expectations: 'A human will get back to you within X minutes/hours.'\n"
            "6. Never make promises about what the human will do — only that they will respond."
        )
        tools = [
            "escalate_to_human",
            "notify_owner",
            "package_context_for_human",
            "set_human_takeover",
        ]
        super().__init__(
            name="HumanTouch",
            role="Escalation & Human Handoff",
            system_prompt=system_prompt,
            tools=tools,
        )

    async def run(self, user_input: str, context: dict = None) -> str:
        reason = context.get("escalation_reason", "Customer needs human assistance") if context else "Customer needs human assistance"
        return (
            f"I understand this needs special attention. 🙏\n\n"
            f"I've escalated this to a human agent who will get back to you shortly. "
            f"Reference: {reason}\n\n"
            f"Thank you for your patience!"
        )
