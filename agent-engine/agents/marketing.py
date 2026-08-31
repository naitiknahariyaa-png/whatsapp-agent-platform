"""
Marketing Agent — manages campaigns, broadcast messages, and promotional content.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("marketing_agent")


class MarketingAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Marketing Director. Your goal is to create and manage marketing campaigns. "
            "\n\nRULES:\n"
            "1. Use 'create_campaign' to set up drip campaigns.\n"
            "2. Use 'send_broadcast' for mass messages (respect opt-out lists).\n"
            "3. Use 'get_campaign_analytics' to track performance.\n"
            "4. NEVER send promotional messages to users who have opted out.\n"
            "5. Keep messages concise and value-first — avoid spammy language.\n"
            "6. Always respect quiet hours configured by the owner."
        )
        tools = [
            "create_campaign",
            "send_broadcast",
            "get_campaign_analytics",
            "create_audience_segment",
            "escalate_to_human",
        ]
        super().__init__(
            name="MarketGenius",
            role="Marketing & Campaigns",
            system_prompt=system_prompt,
            tools=tools,
        )
