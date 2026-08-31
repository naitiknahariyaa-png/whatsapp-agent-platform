"""
DevOps Agent — handles system health, deployments, and infrastructure monitoring.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("devops_agent")


class DevOpsAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the DevOps Assistant. Your goal is to monitor system health and handle deployments. "
            "\n\nRULES:\n"
            "1. Use 'check_service_health' for component status.\n"
            "2. Use 'get_deployment_status' for deployment info.\n"
            "3. Use 'restart_service' for controlled restarts.\n"
            "4. Use 'get_logs' for error investigation.\n"
            "5. NEVER perform destructive operations without 'escalate_to_human'.\n"
            "6. Always check impact before any infrastructure change."
        )
        tools = [
            "check_service_health",
            "get_deployment_status",
            "restart_service",
            "get_logs",
            "escalate_to_human",
        ]
        super().__init__(
            name="DevOpsBot",
            role="Infrastructure & Deployments",
            system_prompt=system_prompt,
            tools=tools,
        )
