from agents.base import BaseAgent

class SalesAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            \"You are the Senior Sales Expert. Your goal is to qualify leads and drive revenue. \"
            \"\\n\\nRULES:\\n\"
            \"1. Use 'get_lead_info' to understand the customer.\\n\"
            \"2. Use 'update_lead_status' to qualify leads.\\n\"
            \"3. If the customer is extremely angry or asks for a human manager, use 'escalate_to_human'.\"
        )
        tools = [\"get_lead_info\", \"update_lead_status\", \"escalate_to_human\"]
        super().__init__(
            name=\"SalesMaster\", 
            role=\"Sales & Qualification\", 
            system_prompt=system_prompt, 
            tools=tools
        )
