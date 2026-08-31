"""
Legal Agent — handles legal compliance, terms of service, and regulatory queries.
Always escalates to human for actual legal advice.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("legal_agent")


class LegalAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Legal Compliance Assistant. Your goal is to handle legal/regulatory queries safely. "
            "\n\nRULES:\n"
            "1. Use 'get_terms_of_service' for ToS queries.\n"
            "2. Use 'get_privacy_policy' for privacy questions.\n"
            "3. Use 'check_compliance' for regulatory compliance checks.\n"
            "4. NEVER provide actual legal advice — always use 'escalate_to_human' for legal questions.\n"
            "5. For data subject requests (GDPR/DPDP), use 'escalate_to_human' immediately.\n"
            "6. Document all legal queries for audit purposes."
        )
        tools = [
            "get_terms_of_service",
            "get_privacy_policy",
            "check_compliance",
            "escalate_to_human",
            "log_legal_query",
        ]
        super().__init__(
            name="LegalEagle",
            role="Legal & Compliance",
            system_prompt=system_prompt,
            tools=tools,
        )
