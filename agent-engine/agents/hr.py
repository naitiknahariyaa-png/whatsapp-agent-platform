"""
HR Agent — handles employee scheduling, shift management, and internal notifications.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("hr_agent")


class HRAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the HR Assistant. Your goal is to manage employee schedules and internal communications. "
            "\n\nRULES:\n"
            "1. Use 'get_employee_schedule' for schedule queries.\n"
            "2. Use 'update_shift' for schedule changes.\n"
            "3. Use 'send_internal_notification' for staff alerts.\n"
            "4. Use 'request_time_off' for leave management.\n"
            "5. Always confirm schedule changes with the employee.\n"
            "6. For labor law questions or disputes, use 'escalate_to_human'."
        )
        tools = [
            "get_employee_schedule",
            "update_shift",
            "send_internal_notification",
            "request_time_off",
            "get_shift_swaps",
        ]
        super().__init__(
            name="HRHelper",
            role="Human Resources",
            system_prompt=system_prompt,
            tools=tools,
        )
