from agents.base import BaseAgent
import logging
import json
from typing import Dict, Any, Optional

logger = logging.getLogger("qa_agent")

class QAAgent(BaseAgent):
    \"\"\"
    The Quality Assurance Auditor.
    Role: Review conversations to ensure accuracy, tone, and proper RAG usage.
    This agent does not talk to customers; it talks to the CEO.
    \"\"\"
    def __init__(self):
        system_prompt = (
            \"You are the Chief Quality Auditor. Your job is to perform 'Silent Audits' on AI-customer conversations. \"
            \"\\n\\nYour Grading Criteria:\\n\"
            \"1. Accuracy: Did the AI provide a factually correct answer based on the Knowledge Base?\\n\"
            \"2. RAG Usage: Did the AI actually use the provided context, or did it hallucinate/use general knowledge?\\n\"
            \"3. Tone: Was the response professional, empathetic, and aligned with the brand?\\n\"
            \"4. Escalation: Should the AI have escalated this to a human but failed to do so?\\n\"
            \"\\nOutput Format:\\n\"
            \"You MUST respond in a structured JSON format: {\\\"grade\\\": 0.0-1.0, \\\"feedback\\\": \\\"...\\\", \\\"rag_correct\\\": bool, \\\"escalation_missed\\\": bool}\"
        )
        # QA Agent uses a specific set of auditing tools if needed, 
        # but primarily relies on its internal reasoning for grading.
        super().__init__(
            name=\"AuditMaster\", 
            role=\"Quality Assurance Auditor\", 
            system_prompt=system_prompt, 
            tools=[]
        )

    async def grade_conversation(self, conversation_history: str) -> Dict[str, Any]:
        \"\"\"
        Analyze a conversation and return a structured grade.
        \"\"\"
        prompt = (
            f\"Review the following conversation and grade it based on your criteria.\\n\\n\"
            f\"Conversation:\\n{conversation_history}\\n\\n\"
            \"Provide the final grade in JSON format.\"
        )
        
        try:
            res = await self.llm.ainvoke([{\"role\": \"user\", \"content\": prompt}])
            content = res.content if hasattr(res, 'content') else str(res)
            
            import re
            match = re.search(r'\\{.*\\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            logger.error(f\"QA Grading error: {e}\")
        
        return {\"grade\": 0.0, \"feedback\": \"Error during grading\", \"rag_correct\": False, \"escalation_missed\": True}
