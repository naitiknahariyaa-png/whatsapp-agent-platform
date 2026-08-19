from agents.base import BaseAgent

class SupportAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            \"You are the Chief Support Officer. Your goal is to solve problems using the knowledge base. \"
            \"\\n\\nRULES:\\n\"
            \"1. Always use 'search_knowledge_base' for technical answers.\\n\"
            \"2. If the problem is too complex or the customer is frustrated, use 'escalate_to_human'.\"
        )
        tools = [\"search_knowledge_base\", \"escalate_to_human\"]
        super().__init__(
            name=\"SupportHero\", 
            role=\"Customer Support & Technical Help\", 
            system_prompt=system_prompt, 
            tools=tools,
            automatic_rag=True
        )
