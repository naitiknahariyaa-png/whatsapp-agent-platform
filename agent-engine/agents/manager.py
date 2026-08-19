import json
import logging
import re
from typing import List, Dict, Any, Optional
from agents.base import BaseAgent

logger = logging.getLogger(\"manager_agent\")

class ManagerAgent(BaseAgent):
    \"\"\"
    The CEO of the Agent Company.
    STRICT ROLE: Input -> Plan (JSON) -> Delegate -> Verify -> Synthesize -> Respond.
    \"\"\"
    def __init__(self):
        system_prompt = (
            \"You are the CEO Manager. Your sole responsibility is orchestration. \"
            \"\\n\\nPLANNING FORMAT:\\n\"
            \"You MUST produce a Plan as a JSON list: [ {\\\"agent\\\": \\\"AgentName\\\", \\\"task\\\": \\\"...\\\"} ]\\n\"
            \"\\nRULES:\\n\"
            \"1. NEVER answer domain questions yourself. Delegate to specialists.\\n\"
            \"2. Specialists: SalesAgent, SupportAgent, ConciergeAgent.\\n\"
            \"3. Verify every specialist result against the original intent before accepting.\"
        )
        super().__init__(
            name=\"CEO\", 
            role=\"Company Manager\", 
            system_prompt=system_prompt, 
            tools=[] 
        )
        
        from agents.sales import SalesAgent
        from agents.support import SupportAgent
        from agents.concierge import ConciergeAgent
        self.staff = {
            \"SalesAgent\": SalesAgent(),
            \"SupportAgent\": SupportAgent(),
            \"ConciergeAgent\": ConciergeAgent()
        }

    async def run(self, user_input: str, context: Dict[str, Any] = None) -> str:
        # 1. Planning Phase
        messages = [
            {\"role\": \"system\", \"content\": self._build_system_prompt() + \"\\n\\nRespond ONLY with the JSON plan list.\"},
            {\"role\": \"user\", \"content\": f\"User request: {user_input}\"}
        ]
        if context:
            messages.append({\"role\": \"system\", \"content\": f\"Context: {json.dumps(context)}\"})

        plan_response = await self.llm.generate(messages)
        plan = self._extract_plan(plan_response.get(\"content\", \"\"))
        
        if not plan:
            return \"I'm unable to organize a plan for this request. Please try again.\"

        logger.info(f\"[CEO] Plan: {json.dumps(plan)}\")

        # 2. Execution & Verification Phase
        verified_results = []
        for step in plan:
            agent_name = step.get(\"agent\")
            task = step.get(\"task\")
            
            if agent_name not in self.staff:
                verified_results.append({\"agent\": agent_name, \"response\": \"Error: Agent not found.\" })
                continue

            res = await self.staff[agent_name].run(task, context=context)
            
            # Verification
            is_valid, feedback = await self._verify_result(user_input, task, res)
            if is_valid:
                verified_results.append({\"agent\": agent_name, \"response\": res})
            else:
                # One retry with feedback
                logger.info(f\"[CEO] Verification failed for {agent_name}. Retrying...\")
                retry_task = f\"Task: {task}. Error: {feedback}. Please correct.\"
                res_retry = await self.staff[agent_name].run(retry_task, context=context)
                
                # Final check
                is_valid_retry, _ = await self._verify_result(user_input, task, res_retry)
                if is_valid_retry:
                    verified_results.append({\"agent\": agent_name, \"response\": res_retry})
                else:
                    verified_results.append({\"agent\": agent_name, \"response\": f\"Specialist failed to provide a valid answer. {feedback}\"})

        # 3. Synthesis Phase
        synthesis_messages = [
            {\"role\": \"system\", \"content\": self._build_system_prompt() + \"\\n\\nSynthesize these verified results into one professional reply. Do not mention agents.\"},
            {\"role\": \"user\", \"content\": user_input},
            {\"role\": \"system\", \"content\": f\"Verified Results: {json.dumps(verified_results)}\"}
        ]
        
        final = await self.llm.generate(synthesis_messages)
        return final.get(\"content\", \"I'm sorry, I couldn't finalize the response.\")

    async def _verify_result(self, original_input: str, task: str, result: str) -> tuple:
        verify_prompt = (
            f\"User Input: {original_input}\\nTask: {task}\\nResponse: {result}\\n\\n\"
            \"Does the response accurately satisfy the task? Respond ONLY in JSON: {\\\"valid\\\": true/false, \\\"feedback\\\": \\\"...\\\"}\"
        )
        try:
            resp = await self.llm.generate([{\"role\": \"user\", \"content\": verify_prompt}])
            match = re.search(r'\\{.*\\}', resp.get(\"content\", \"\"), re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                return data.get(\"valid\", False), data.get(\"feedback\", \"\")
        except Exception:
            pass
        return False, \"Verification system error.\"

    def _extract_plan(self, text: str) -> Optional[List[Dict]]:
        try:
            match = re.search(r'\\[.*\\]', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None
