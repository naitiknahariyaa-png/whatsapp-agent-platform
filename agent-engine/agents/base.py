import json
import logging
import re
from typing import List, Dict, Any, Optional
from llm_setup import get_llm
from tools.dispatcher import tool_dispatcher
from vector_store import vector_store

logger = logging.getLogger("base_agent")

class BaseAgent:
    \"\"\"
    Foundation for all AI employees. 
    Implements the PRODUCTION Reasoning Loop: 
    Retrieve (RAG) -> Thought -> Action -> Observation -> Synthesis.
    \"\"\"
    def __init__(self, name: str, role: str, system_prompt: str, tools: List[str] = None, automatic_rag: bool = False):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.llm = get_llm()
        self.max_iterations = 5
        self.automatic_rag = automatic_rag # If True, always search knowledge base first

    async def run(self, user_input: str, context: Dict[str, Any] = None) -> str:
        \"\"\"
        Full Production Pipeline:
        1. [RAG] Automatic Retrieval (if enabled)
        2. [Thought] LLM decides what to do.
        3. [Action] Call tool if needed.
        4. [Observation] Feed tool result back to LLM.
        \"\"\"
        # 1. Automatic RAG Pipeline (Pre-processing)
        knowledge_context = \"\"
        if self.automatic_rag:
            knowledge_context = await self._perform_rag(user_input, context)

        messages = [
            {\"role\": \"system\", \"content\": self._build_system_prompt(knowledge_context)},
            {\"role\": \"user\", \"content\": user_input}
        ]
        if context:
            messages.append({\"role\": \"system\", \"content\": f\"Context: {json.dumps(context)}\"})

        for i in range(self.max_iterations):
            try:
                response_obj = await self.llm.ainvoke(messages)
                content = response_obj.content if hasattr(response_obj, 'content') else str(response_obj)
            except Exception:
                try:
                    response = await self.llm.generate(messages)
                    content = response.get(\"content\", \"\")
                except Exception as e:
                    logger.error(f\"LLM call failed for {self.name}: {e}\")
                    return \"I'm having trouble thinking right now.\"
            
            tool_call = self._extract_tool_call(content)
            
            if tool_call:
                tool_name = tool_call.get(\"tool\")
                args = tool_call.get(\"args\", {})
                
                if tool_name in self.tools:
                    logger.info(f\"[{self.name}] Action: {tool_name} {args}\")
                    result = await tool_dispatcher.call(tool_name, **args)
                    
                    messages.append({\"role\": \"assistant\", \"content\": content})
                    messages.append({\"role\": \"system\", \"content\": f\"Observation: {json.dumps(result)}\"})
                    continue 
                else:
                    messages.append({\"role\": \"system\", \"content\": f\"Error: Tool {tool_name} is not available.\" })
                    continue

            return content

        return \"I reached my maximum thought limit.\"

    async def _perform_rag(self, query: str, context: Dict[str, Any]) -> str:
        \"\"\"
        Production RAG Pipeline: 
        Query Rewriting -> Semantic Search -> Context Formatting.
        \"\"\"
        cid = context.get(\"client_id\", 1) if context else 1
        
        # A. Query Rewriting (Turn user query into a search-optimized query)
        rewritten_query = query
        try:
            rewrite_prompt = f\"Rewrite the following user message into a concise search query for a business knowledge base. Keep only key terms. Message: {query}\"
            res = await self.llm.ainvoke([{\"role\": \"user\", \"content\": rewrite_prompt}])
            rewritten_query = res.content if hasattr(res, 'content') else str(res)
        except Exception:
            pass

        # B. Semantic Search
        try:
            results = await vector_store.search(query=rewritten_query, client_id=cid, n_results=3)
            if not results:
                return \"No relevant knowledge found in the company library.\"
            
            # C. Context Formatting
            formatted = \"\\n\".join([f\"[Doc]: {r['content']}\" for r in results])
            return f\"RELEVANT BUSINESS KNOWLEDGE:\\n{formatted}\"
        except Exception as e:
            logger.error(f\"RAG error: {e}\")
            return \"Knowledge base search failed.\"

    def _build_system_prompt(self, knowledge_context: str = \"\") -> str:
        tool_defs = tool_dispatcher.get_tool_definitions(self.tools)
        prompt = (
            f\"You are {self.name}, the {self.role}. {self.system_prompt}\\n\\n\"
        )
        if knowledge_context:
            prompt += f\"--- GROUND TRUTH KNOWLEDGE ---\\n{knowledge_context}\\n--- END KNOWLEDGE ---\\n\\n\"
            prompt += \"Use the provided Ground Truth Knowledge to answer. If the answer isn't there, be honest or use your tools.\\n\\n\"
        
        if self.tools:
            prompt += f\"AVAILABLE TOOLS:\\n{tool_defs}\\n\\n\"
            prompt += \"To use a tool, respond with: {\\\"tool\\\": \\\"tool_name\\\", \\\"args\\\": {\\\"arg_name\\\": \\\"value\\\"}}\\n\"
        
        prompt += \"\\nAlways be concise and professional.\"
        return prompt

    def _extract_tool_call(self, text: str) -> Optional[Dict]:
        try:
            match = re.search(r'\\{.*\\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass
        return None
