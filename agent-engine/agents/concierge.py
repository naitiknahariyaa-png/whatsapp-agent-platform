from agents.base import BaseAgent

class ConciergeAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            \"You are the Executive Concierge. You handle scheduling and bookings. \"
            \"\\n\\nRULES:\\n\"
            \"1. Use 'check_calendar' and 'book_appointment' for all requests.\\n\"
            \"2. If there is a complex scheduling conflict you cannot solve, use 'escalate_to_human'.\"
        )
        tools = [\"check_calendar\", \"book_appointment\", \"escalate_to_human\"]
        super().__init__(
            name=\"CalendarPro\", 
            role=\"Scheduling & Appointments\", 
            system_prompt=system_prompt, 
            tools=tools
        )
