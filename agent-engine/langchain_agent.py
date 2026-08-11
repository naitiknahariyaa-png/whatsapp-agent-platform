"""
LangChain Agent - Advanced AI agent with tools, memory, and vector store
"""
import json
import asyncio
from typing import List, Dict, Optional, Any
from datetime import datetime

from config import settings
from vector_store import search_knowledge, add_knowledge_item, get_collection_stats

try:
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.output_parsers import StrOutputParser
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    print("[!] LangChain core not installed. Run: pip install langchain langchain-groq langchain-core")


class LangChainAgent:
    """Advanced AI agent using LangChain with tools and memory."""

    def __init__(self):
        self.llm = None
        self._init_llm()

    def _init_llm(self):
        """Initialize the LLM with fallback using centralized llm_setup."""
        if not LANGCHAIN_AVAILABLE:
            return

        try:
            from llm_setup import get_llm, get_provider_status
            self.llm = get_llm()
            status = get_provider_status()
            active = [k for k, v in status.items() if v.get("available")]
            if active:
                print(f"[v] LangChain agent using LLM provider: {active[0]}")
            else:
                print("[i] LangChain agent initialized with MockLLM (no real LLM available)")
        except ImportError as e:
            print(f"[!] llm_setup not available: {e}")
        except Exception as e:
            print(f"[!] Failed to init LangChain LLM: {e}")

    @property
    def available(self) -> bool:
        if self.llm is None:
            return False
        llm_type = getattr(self.llm, '_llm_type', '')
        return llm_type != 'mock'

    async def generate_response(self, message: str, history: List[Dict], client_id: int = 1,
                                business_context: Dict = None) -> str:
        """Generate a response using LangChain with knowledge base retrieval."""
        if not self.available or self.llm is None:
            return self._fallback_response(message, business_context)

        # Retrieve relevant knowledge
        knowledge = search_knowledge(client_id, message, n_results=3)
        knowledge_text = ""
        if knowledge:
            knowledge_text = "\n\nRelevant knowledge:\n" + "\n".join(
                [f"- {k['content'][:200]}" for k in knowledge]
            )

        # Build conversation history
        history_text = ""
        if history:
            history_text = "\n".join([
                f"{'Customer' if h['direction'] == 'incoming' else 'Assistant'}: {h['content']}"
                for h in history[-5:]
            ])

        # Business context
        biz_name = (business_context or {}).get("name", "the business")
        biz_type = (business_context or {}).get("business_type", "general")

        system_prompt = f"""You are a helpful WhatsApp AI assistant for {biz_name}, a {biz_type} business in India.
You speak in a friendly, professional tone. You can respond in English, Hindi, or Hinglish based on the customer's language.

Your capabilities:
- Answer questions about products, services, pricing, and business hours
- Help book appointments
- Take orders
- Provide business information
- Escalate to human agent when needed

Rules:
- Be concise and helpful
- Use emojis sparingly
- If you don't know something, say so honestly
- Never make up information
- For complex issues, suggest talking to a human agent
{knowledge_text}"""

        messages = [SystemMessage(content=system_prompt)]

        if history_text:
            messages.append(SystemMessage(content=f"Previous conversation:\n{history_text}"))

        messages.append(HumanMessage(content=message))

        try:
            response = await asyncio.to_thread(self.llm.invoke, messages)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            print(f"[!] LangChain generation error: {e}")
            return self._fallback_response(message, business_context)

    def _fallback_response(self, message: str, business_context: Dict = None) -> str:
        """Fallback keyword-based response when LLM is unavailable."""
        msg = message.lower()
        biz_name = (business_context or {}).get("name", "our business")

        if any(w in msg for w in ["hi", "hello", "namaste", "hey"]):
            return f"👋 Hello! Welcome to {biz_name}. How can I help you today?"
        if any(w in msg for w in ["price", "cost", "rate", "fees", "kitna"]):
            return f"💰 For pricing details, please visit our storefront or ask our team. We have competitive rates!"
        if any(w in msg for w in ["book", "appointment", "schedule", "slot"]):
            return "📅 I can help you book an appointment! Please tell me your preferred date and time."
        if any(w in msg for w in ["order", "buy", "purchase"]):
            return "🛒 Great! Please tell me what you'd like to order and I'll help you place it."
        if any(w in msg for w in ["human", "agent", "person", "help"]):
            return "🤝 I'll connect you with a human agent shortly. Please hold on!"
        if any(w in msg for w in ["bye", "goodbye", "thank"]):
            return f"🙏 Thank you for contacting {biz_name}! Have a great day!"
        return f"Thanks for your message! I'm here to help with {biz_name}. Could you tell me more about what you need?"


# Global agent instance
langchain_agent = LangChainAgent()