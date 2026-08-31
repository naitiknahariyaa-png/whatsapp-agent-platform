"""
LLM Cost/Model Routing
======================

Routes tasks to the most cost-effective model based on task complexity:
- Classification/Intent detection → Cheap fast model
- Manager planning → Best model
- Sales/Support generation → Best model
- Simple Q&A → Cheap model
- Complex reasoning → Best model

All usage is tracked for billing/optimization.
"""
import os
import logging
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
from functools import lru_cache

logger = logging.getLogger("model_router")

try:
    from llm_setup import get_llm as _get_llm_legacy
    from config import settings
except ImportError:
    settings = None


class TaskType(Enum):
    """Types of LLM tasks with different complexity/cost requirements."""
    CLASSIFICATION = "classification"          # Intent, sentiment, routing
    EXTRACTION = "extraction"                  # Entity extraction, slot filling
    SIMPLE_QA = "simple_qa"                    # FAQ, basic questions
    CONVERSATION = "conversation"              # General chat
    PLANNING = "planning"                      # Manager planning, strategy
    GENERATION = "generation"                  # Sales/Support responses
    REASONING = "reasoning"                    # Complex multi-step reasoning
    SUMMARIZATION = "summarization"            # Conversation summarization
    VERIFICATION = "verification"              # Tool result verification


class ModelTier(Enum):
    CHEAP = "cheap"
    STANDARD = "standard"
    PREMIUM = "premium"


@dataclass
class ModelConfig:
    provider: str
    model: str
    tier: ModelTier
    max_tokens: int = 2048
    temperature: float = 0.3


# Default model mappings (can be overridden via env)
DEFAULT_MODEL_MAP: Dict[TaskType, ModelConfig] = {
    TaskType.CLASSIFICATION: ModelConfig(
        provider="groq",
        model=os.getenv("CLASSIFICATION_MODEL", "llama-3.1-8b-instant"),
        tier=ModelTier.CHEAP,
        max_tokens=512,
        temperature=0.1,
    ),
    TaskType.EXTRACTION: ModelConfig(
        provider="groq",
        model=os.getenv("EXTRACTION_MODEL", "llama-3.1-8b-instant"),
        tier=ModelTier.CHEAP,
        max_tokens=512,
        temperature=0.1,
    ),
    TaskType.SIMPLE_QA: ModelConfig(
        provider="groq",
        model=os.getenv("SIMPLE_QA_MODEL", "llama-3.1-8b-instant"),
        tier=ModelTier.CHEAP,
        max_tokens=1024,
        temperature=0.3,
    ),
    TaskType.CONVERSATION: ModelConfig(
        provider="groq",
        model=os.getenv("CONVERSATION_MODEL", "llama-3.1-8b-instant"),
        tier=ModelTier.CHEAP,
        max_tokens=1024,
        temperature=0.4,
    ),
    TaskType.PLANNING: ModelConfig(
        provider="groq",
        model=os.getenv("PLANNING_MODEL", "llama-3.3-70b-versatile"),
        tier=ModelTier.PREMIUM,
        max_tokens=2048,
        temperature=0.2,
    ),
    TaskType.GENERATION: ModelConfig(
        provider="groq",
        model=os.getenv("GENERATION_MODEL", "llama-3.3-70b-versatile"),
        tier=ModelTier.PREMIUM,
        max_tokens=2048,
        temperature=0.5,
    ),
    TaskType.REASONING: ModelConfig(
        provider="groq",
        model=os.getenv("REASONING_MODEL", "llama-3.3-70b-versatile"),
        tier=ModelTier.PREMIUM,
        max_tokens=4096,
        temperature=0.2,
    ),
    TaskType.SUMMARIZATION: ModelConfig(
        provider="groq",
        model=os.getenv("SUMMARIZATION_MODEL", "llama-3.1-8b-instant"),
        tier=ModelTier.STANDARD,
        max_tokens=1024,
        temperature=0.1,
    ),
    TaskType.VERIFICATION: ModelConfig(
        provider="groq",
        model=os.getenv("VERIFICATION_MODEL", "llama-3.3-70b-versatile"),
        tier=ModelTier.PREMIUM,
        max_tokens=1024,
        temperature=0.1,
    ),
}


class ModelRouter:
    """
    Routes LLM calls to the appropriate model based on task type.
    Tracks usage for cost monitoring.
    """

    def __init__(self):
        self._model_cache: Dict[str, Any] = {}
        self._usage_stats: Dict[str, Dict[str, int]] = {}

    def get_model_for_task(self, task_type: TaskType) -> ModelConfig:
        """Get the appropriate model configuration for a task type."""
        return DEFAULT_MODEL_MAP.get(task_type, DEFAULT_MODEL_MAP[TaskType.CONVERSATION])

    def get_llm(self, task_type: TaskType, override_model: Optional[str] = None):
        """Get an LLM instance for the given task type."""
        config = self.get_model_for_task(task_type)
        model_key = f"{config.provider}/{config.model}"

        if override_model:
            model_key = override_model

        if model_key not in self._model_cache:
            self._model_cache[model_key] = self._create_llm(config, override_model)

        return self._model_cache[model_key]

    def _create_llm(self, config: ModelConfig, override_model: Optional[str] = None):
        """Create an LLM instance for the given config."""
        model_name = override_model or config.model

        if config.provider == "groq":
            from langchain_groq import ChatGroq
            api_key = os.getenv("GROQ_API_KEY") or (settings.groq_api_key if settings else "")
            return ChatGroq(
                model=model_name,
                api_key=api_key,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        elif config.provider == "openai":
            from langchain_openai import ChatOpenAI
            api_key = os.getenv("OPENAI_API_KEY") or (settings.openai_api_key if settings else "")
            return ChatOpenAI(
                model=model_name,
                api_key=api_key,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        elif config.provider == "ollama":
            from langchain_ollama import ChatOllama
            base_url = os.getenv("OLLAMA_BASE_URL") or (settings.ollama_base_url if settings else "http://localhost:11434")
            return ChatOllama(
                model=model_name,
                base_url=base_url,
                temperature=config.temperature,
                num_predict=config.max_tokens,
            )
        else:
            raise ValueError(f"Unknown provider: {config.provider}")

    def record_usage(self, task_type: TaskType, model: str, prompt_tokens: int, completion_tokens: int):
        """Record usage for cost tracking."""
        key = f"{task_type.value}:{model}"
        if key not in self._usage_stats:
            self._usage_stats[key] = {"prompt": 0, "completion": 0, "calls": 0}
        self._usage_stats[key]["prompt"] += prompt_tokens
        self._usage_stats[key]["completion"] += completion_tokens
        self._usage_stats[key]["calls"] += 1

    def get_usage_stats(self) -> Dict[str, Dict[str, int]]:
        return self._usage_stats.copy()

    def estimate_cost(self, task_type: TaskType, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost in USD for a task (rough approximation)."""
        config = self.get_model_for_task(task_type)
        # Rough pricing per 1K tokens (update as needed)
        pricing = {
            "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
            "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 5.00, "output": 15.00},
        }
        model_pricing = pricing.get(config.model, {"input": 0.10, "output": 0.20})
        cost = (prompt_tokens / 1000 * pricing["input"]) + (completion_tokens / 1000 * pricing["output"])
        return cost


# Global instance
model_router = ModelRouter()


# Convenience functions for common tasks
def get_classification_llm():
    return model_router.get_llm(TaskType.CLASSIFICATION)

def get_extraction_llm():
    return model_router.get_llm(TaskType.EXTRACTION)

def get_planning_llm():
    return model_router.get_llm(TaskType.PLANNING)

def get_generation_llm():
    return model_router.get_llm(TaskType.GENERATION)

def get_reasoning_llm():
    return model_router.get_llm(TaskType.REASONING)

def get_simple_qa_llm():
    return model_router.get_llm(TaskType.SIMPLE_QA)

def get_verification_llm():
    return model_router.get_llm(TaskType.VERIFICATION)