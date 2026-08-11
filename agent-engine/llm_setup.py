"""
LLM Setup - Multi-provider support with intelligent fallback chain.
Providers: Groq (primary) → Ollama (local) → OpenAI (optional) → MockLLM (last resort)
"""
import os
import sys
import asyncio
import logging
from typing import Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import AIMessage
from config import settings

logger = logging.getLogger("llm_setup")

# Provider availability flags
_PROVIDER_STATUS = {
    "groq": {"available": False, "error": None},
    "ollama": {"available": False, "error": None},
    "openai": {"available": False, "error": None},
}


def _init_groq() -> Optional[BaseChatModel]:
    """Initialize Groq LLM."""
    try:
        from langchain_groq import ChatGroq
        api_key = settings.groq_api_key
        if not api_key or api_key.strip() in ("", "your_groq_api_key_here", "your_groq_api_key"):
            _PROVIDER_STATUS["groq"]["error"] = "API key not configured"
            return None
        llm = ChatGroq(
            model=settings.llm_model or "llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=1024,
            groq_api_key=api_key,
        )
        _PROVIDER_STATUS["groq"]["available"] = True
        logger.info("[v] Groq LLM initialized: %s", settings.llm_model)
        return llm
    except ImportError:
        _PROVIDER_STATUS["groq"]["error"] = "langchain-groq not installed"
        return None
    except Exception as e:
        _PROVIDER_STATUS["groq"]["error"] = str(e)
        logger.warning("[!] Groq init failed: %s", e)
        return None


def _init_ollama() -> Optional[BaseChatModel]:
    """Initialize Ollama LLM."""
    try:
        from langchain_ollama import ChatOllama
        base_url = settings.ollama_base_url or "http://localhost:11434"
        model = settings.llm_model or "llama3.2"
        llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=0.3,
            num_predict=1024,
        )
        _PROVIDER_STATUS["ollama"]["available"] = True
        logger.info("[v] Ollama LLM initialized: %s at %s", model, base_url)
        return llm
    except ImportError:
        _PROVIDER_STATUS["ollama"]["error"] = "langchain-ollama not installed"
        return None
    except Exception as e:
        _PROVIDER_STATUS["ollama"]["error"] = str(e)
        logger.warning("[!] Ollama init failed: %s", e)
        return None


def _init_openai() -> Optional[BaseChatModel]:
    """Initialize OpenAI LLM (optional fallback)."""
    try:
        from langchain_openai import ChatOpenAI
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.strip() in ("", "your_openai_api_key_here"):
            _PROVIDER_STATUS["openai"]["error"] = "API key not configured"
            return None
        llm = ChatOpenAI(
            model=settings.openai_model or "gpt-4o-mini",
            temperature=0.3,
            max_tokens=1024,
            api_key=api_key,
        )
        _PROVIDER_STATUS["openai"]["available"] = True
        logger.info("[v] OpenAI LLM initialized: %s", settings.openai_model or "gpt-4o-mini")
        return llm
    except ImportError:
        _PROVIDER_STATUS["openai"]["error"] = "langchain-openai not installed"
        return None
    except Exception as e:
        _PROVIDER_STATUS["openai"]["error"] = str(e)
        logger.warning("[!] OpenAI init failed: %s", e)
        return None


class MockLLM(BaseChatModel):
    """Keyword-based mock LLM for testing without external APIs."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1].content if messages else ""
        user_msg = ""
        lines = last.strip().split("\n")
        for line in reversed(lines):
            if line.strip().startswith("User message:"):
                user_msg = line.split("User message:", 1)[1].strip()
                break
        if not user_msg:
            lines = [l.strip() for l in lines if l.strip()]
            for line in reversed(lines):
                if not any(line.startswith(p) for p in ["-", "Return", "JSON", "Previous", "User's", "Generate", "You are", "Keep it"]):
                    user_msg = line
                    break
            if not user_msg and lines:
                user_msg = lines[-1]

        msg = user_msg.lower()
        if any(w in msg for w in ["hello", "hi", "hey", "namaste", "namaskar", "good morning", "good evening"]):
            resp = "Namaste! Main aapka AI assistant hoon. Main aapki kaise madad kar sakta hoon?"
        elif any(w in msg for w in ["bye", "goodbye", "alvida", "dhanyavad", "thank", "shukriya", "phir milenge"]):
            resp = "Dhanyavad! Koi aur madad chahiye toh bataiye. Shubh din!"
        elif any(w in msg for w in ["appointment", "book", "schedule", "meeting", "slot", "visit", "table"]):
            resp = "Ji, appointment book karne ke liye kya aap date aur time bata sakte hain?"
        elif any(w in msg for w in ["price", "cost", "rate", "kitna", "charges", "fees", "fee", "pricing"]):
            resp = "Pricing ke baare mein jaankari ke liye, kya aap bata sakte hain ki aapko kis service mein interest hai?"
        elif any(w in msg for w in ["help", "support", "problem", "issue", "error", "not working"]):
            resp = "Mujhe aapki problem samajhne mein khushi hogi. Kya aap thoda detail mein bata sakte hain?"
        elif any(w in msg for w in ["fever", "cough", "cold", "headache", "pain", "bukhar", "khansi", "sardi", "dard"]):
            resp = "Kya aap apne symptoms detail mein bata sakte hain? Emergency hai toh 108 dial karein!"
        elif any(w in msg for w in ["prescription", "dawai", "medicine"]):
            resp = "Prescription renewal ke liye purani prescription ki photo bheje."
        elif any(w in msg for w in ["lab", "report", "test", "blood"]):
            resp = "Lab reports ke liye report ki photo/PDF bhej sakte hain."
        elif any(w in msg for w in ["case", "court", "legal", "mukadma", "property dispute", "divorce", "criminal"]):
            resp = "Kya aap case ke baare mein thoda aur bata sakte hain?"
        elif any(w in msg for w in ["itr", "tax", "gst", "income tax", "return filing", "deadline"]):
            resp = "ITR filing ke liye main aapki madad kar sakta hoon. Kya aap bata sakte hain ki aapki income source kya hai?"
        elif any(w in msg for w in ["menu", "food", "khana", "order", "delivery"]):
            resp = "Humare menu mein veg aur non-veg dono options hain. Kya aap kuch specific dekhna chahenge?"
        elif any(w in msg for w in ["document", "upload", "file", "pdf", "photo", "image"]):
            resp = "Ji, aap document upload kar sakte hain. Bas file forward karein, main automatically process kar lunga!"
        elif any(w in msg for w in ["interested", "buy", "purchase", "subscribe", "chahiye", "lagna"]):
            resp = "Bahut achha! Aap humari services mein interest dikha rahe hain. Kya aap apna naam aur city bata sakte hain?"
        else:
            resp = f"Main samajh gaya. Aapne kaha: '{last}'. Main aapki kaise madad kar sakta hoon?"

        message = AIMessage(content=resp)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock"


def get_llm() -> BaseChatModel:
    """
    Get the best available LLM with fallback chain.
    Priority: Groq → Ollama → OpenAI → MockLLM
    """
    provider = (settings.llm_provider or "groq").lower().strip()

    # If explicitly configured, try that provider first
    if provider == "groq":
        llm = _init_groq()
        if llm:
            return llm
    elif provider == "ollama":
        llm = _init_ollama()
        if llm:
            return llm
    elif provider == "openai":
        llm = _init_openai()
        if llm:
            return llm

    # Fallback chain: try all available providers
    if provider != "groq":
        llm = _init_groq()
        if llm:
            logger.info("[i] Falling back to Groq (primary provider unavailable)")
            return llm

    if provider not in ("groq", "ollama"):
        llm = _init_ollama()
        if llm:
            logger.info("[i] Falling back to Ollama (local fallback)")
            return llm

    if provider not in ("groq", "ollama", "openai"):
        llm = _init_openai()
        if llm:
            logger.info("[i] Falling back to OpenAI")
            return llm

    # Last resort: MockLLM
    logger.warning("[!] No LLM provider available. Using MockLLM for testing.")
    logger.warning("[!] Configure GROQ_API_KEY, Ollama, or OpenAI for full AI functionality.")
    return MockLLM()


def get_provider_status() -> dict:
    """Return status of all LLM providers for diagnostics."""
    return _PROVIDER_STATUS


def reset_provider_status():
    """Reset provider status (useful for testing)."""
    for key in _PROVIDER_STATUS:
        _PROVIDER_STATUS[key] = {"available": False, "error": None}
