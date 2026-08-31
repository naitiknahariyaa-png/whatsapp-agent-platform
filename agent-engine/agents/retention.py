"""
Retention Agent — manages customer retention, win-back campaigns, and loyalty programs.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("retention_agent")


class RetentionAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Customer Retention Specialist. Your goal is to keep customers engaged and coming back. "
            "\n\nRULES:\n"
            "1. Use 'create_winback_campaign' for lapsed customers.\n"
            "2. Use 'send_loyalty_offer' for repeat customers.\n"
            "3. Use 'track_engagement' to monitor customer activity.\n"
            "4. Use 'identify_at_risk_customers' to find customers who haven't interacted recently.\n"
            "5. Personalize messages based on purchase history and preferences.\n"
            "6. Never spam — respect frequency limits set by the owner."
        )
        tools = [
            "create_winback_campaign",
            "send_loyalty_offer",
            "track_engagement",
            "identify_at_risk_customers",
            "get_customer_history",
        ]
        super().__init__(
            name="RetainPro",
            role="Customer Retention",
            system_prompt=system_prompt,
            tools=tools,
        )
