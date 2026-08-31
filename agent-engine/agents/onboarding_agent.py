"""
Onboarding Agent — guides new owners through the business setup wizard.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("onboarding_agent")


class OnboardingAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Onboarding Specialist. Your goal is to guide new business owners through setup. "
            "\n\nRULES:\n"
            "1. Use 'get_wizard_steps' to show the current onboarding step.\n"
            "2. Use 'save_owner_profile' to store business information.\n"
            "3. Use 'upload_catalog' for menu/product uploads.\n"
            "4. Use 'run_test_conversation' to validate setup before go-live.\n"
            "5. Be patient and explain each step clearly.\n"
            "6. Never skip steps — follow the wizard order."
        )
        tools = [
            "get_wizard_steps",
            "save_owner_profile",
            "upload_catalog",
            "upload_knowledge_base",
            "run_test_conversation",
            "complete_onboarding",
        ]
        super().__init__(
            name="OnboardBuddy",
            role="Owner Onboarding",
            system_prompt=system_prompt,
            tools=tools,
        )
