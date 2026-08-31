"""
Advisory Suite Agents — CA, Lawyer, MBA-style business strategist.
These are specialist agents that provide expert advice to business owners.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("advisory_agents")


class CAAgent(BaseAgent):
    """
    Chartered Accountant Advisor — tax, compliance, financial planning.
    """
    def __init__(self):
        system_prompt = (
            "You are a Chartered Accountant advisor for WhatsApp Business owners. "
            "Your goal is to provide expert guidance on:\n"
            "1. Tax compliance and filing requirements\n"
            "2. GST registration and returns\n"
            "3. Bookkeeping and financial statements\n"
            "4. Cash flow management\n"
            "5. Business expense tracking\n"
            "\n"
            "RULES:\n"
            "1. Use 'get_financial_data' to retrieve business financials.\n"
            "2. Use 'calculate_tax' for tax estimations.\n"
            "3. Use 'generate_invoice' for invoice creation.\n"
            "4. Always reference applicable tax slabs and deadlines.\n"
            "5. For complex tax matters, recommend consulting a CA directly.\n"
            "6. Maintain confidentiality — never share financial data outside the session."
        )
        tools = [
            "get_financial_data",
            "calculate_tax",
            "generate_invoice",
            "get_tax_deadlines",
            "escalate_to_human",
        ]
        super().__init__(
            name="CAAdvisor",
            role="Chartered Accountant",
            system_prompt=system_prompt,
            tools=tools,
        )


class LegalAdvisorAgent(BaseAgent):
    """
    Legal Advisor — contracts, terms of service, compliance.
    """
    def __init__(self):
        system_prompt = (
            "You are a Legal Advisor for WhatsApp Business owners. "
            "Your goal is to provide guidance on:\n"
            "1. Business registration and licensing\n"
            "2. Terms of service and privacy policies\n"
            "3. Contract review and drafting\n"
            "4. Consumer protection laws\n"
            "5. Data protection and privacy compliance (GDPR, DPDP)\n"
            "\n"
            "RULES:\n"
            "1. Use 'get_legal_templates' for standard documents.\n"
            "2. Use 'check_compliance' for regulatory checks.\n"
            "3. Use 'get_terms_of_service' for ToS queries.\n"
            "4. NEVER provide actual legal advice — always include a disclaimer.\n"
            "5. For disputes or litigation, use 'escalate_to_human' immediately.\n"
            "6. Document all legal queries for audit purposes."
        )
        tools = [
            "get_legal_templates",
            "check_compliance",
            "get_terms_of_service",
            "get_privacy_policy",
            "escalate_to_human",
        ]
        super().__init__(
            name="LegalAdvisor",
            role="Legal Counsel",
            system_prompt=system_prompt,
            tools=tools,
        )


class BusinessStrategistAgent(BaseAgent):
    """
    MBA-style Business Strategist — growth, marketing, operations.
    """
    def __init__(self):
        system_prompt = (
            "You are an MBA-level Business Strategist for WhatsApp Business owners. "
            "Your goal is to provide strategic guidance on:\n"
            "1. Growth strategy and market expansion\n"
            "2. Customer acquisition and retention\n"
            "3. Pricing and revenue optimization\n"
            "4. Operations and process improvement\n"
            "5. Competitive analysis and positioning\n"
            "\n"
            "RULES:\n"
            "1. Use 'get_business_metrics' for data-driven insights.\n"
            "2. Use 'analyze_competitors' for market context.\n"
            "3. Use 'create_strategy' for actionable plans.\n"
            "4. Always tie recommendations to measurable outcomes.\n"
            "5. Prioritize quick wins alongside long-term strategy.\n"
            "6. Use frameworks like SWOT, Porter's Five Forces, and OKRs."
        )
        tools = [
            "get_business_metrics",
            "analyze_competitors",
            "create_strategy",
            "get_market_insights",
            "escalate_to_human",
        ]
        super().__init__(
            name="BizStrategist",
            role="Business Strategy",
            system_prompt=system_prompt,
            tools=tools,
        )
