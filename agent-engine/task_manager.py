"""
Task Manager - Runs AI sub-tasks in parallel using asyncio.gather.
Each sub-task is a plugin with priority and timeout settings.
Handles partial failures gracefully.
"""
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime, timezone

logger = logging.getLogger("task_manager")


class TaskResult:
    """Result of a parallel sub-task execution."""
    def __init__(self, task_name: str, success: bool, data: Any = None, error: str = None, duration_ms: float = 0):
        self.task_name = task_name
        self.success = success
        self.data = data
        self.error = error
        self.duration_ms = duration_ms

    def to_dict(self) -> Dict:
        return {
            "task": self.task_name,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }


class TaskManager:
    """
    Runs multiple AI sub-tasks in parallel.
    Each task is an async callable that takes a context dict and returns a result.
    """

    def __init__(self, default_timeout: float = 15.0):
        self.default_timeout = default_timeout
        self._tasks: Dict[str, Callable] = {}
        self._timeouts: Dict[str, float] = {}

    def register(self, name: str, func: Callable, timeout: float = None):
        """Register a sub-task function. Func signature: async def func(context: Dict) -> Any"""
        self._tasks[name] = func
        self._timeouts[name] = timeout or self.default_timeout

    def unregister(self, name: str):
        self._tasks.pop(name, None)
        self._timeouts.pop(name, None)

    async def _run_single(self, name: str, context: Dict) -> TaskResult:
        """Run a single task with timeout and error handling."""
        start = time.monotonic()
        func = self._tasks.get(name)
        if not func:
            return TaskResult(name, False, error="Task not registered")

        try:
            result = await asyncio.wait_for(func(context), timeout=self._timeouts.get(name, self.default_timeout))
            duration = (time.monotonic() - start) * 1000
            return TaskResult(name, True, data=result, duration_ms=duration)
        except asyncio.TimeoutError:
            duration = (time.monotonic() - start) * 1000
            logger.warning(f"[!] Task '{name}' timed out after {self._timeouts.get(name, self.default_timeout)}s")
            return TaskResult(name, False, error="timeout", duration_ms=duration)
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error(f"[!] Task '{name}' failed: {e}")
            return TaskResult(name, False, error=str(e), duration_ms=duration)

    async def run_all(self, context: Dict, task_names: Optional[List[str]] = None) -> Dict[str, TaskResult]:
        """
        Run all (or specified) tasks in parallel.
        Returns dict of task_name -> TaskResult.
        """
        names = task_names or list(self._tasks.keys())
        tasks = []
        for name in names:
            if name not in self._tasks:
                continue
            if self._timeouts.get(name, self.default_timeout) > 10:
                tasks.append(self._run_single_arq(name, context))
            else:
                tasks.append(self._run_single(name, context))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for name, result in zip([n for n in names if n in self._tasks], results):
            if isinstance(result, TaskResult):
                output[name] = result
            else:
                output[name] = TaskResult(name, False, error=str(result))
        return output

    async def _run_single_arq(self, name: str, context: Dict) -> TaskResult:
        """Run a long-running task via ARQ."""
        start = time.monotonic()
        try:
            from arq_worker import enqueue_job
            job_id = await enqueue_job(f"task_{name}", context)
            duration = (time.monotonic() - start) * 1000
            return TaskResult(name, True, data={"job_id": job_id}, duration_ms=duration)
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.error(f"[!] ARQ fallback for task '{name}' failed: {e}")
            return TaskResult(name, False, error=str(e), duration_ms=duration)

    async def submit_to_arq(self, task_name: str, context: Dict) -> str:
        """Submit a background job to ARQ."""
        from arq_worker import enqueue_job
        return await enqueue_job(f"task_{task_name}", context)

    def get_successful(self, results: Dict[str, TaskResult]) -> Dict[str, Any]:
        """Extract only successful task data."""
        return {name: r.data for name, r in results.items() if r.success}

    def get_failed(self, results: Dict[str, TaskResult]) -> Dict[str, str]:
        """Extract failed task errors."""
        return {name: r.error for name, r in results.items() if not r.success}


# ---------------------------------------------------------------------------
# Built-in sub-tasks
# ---------------------------------------------------------------------------

async def sentiment_task(context: Dict) -> Dict:
    """Analyze sentiment of the incoming message."""
    try:
        from services.ai_powerups import sentiment_analyzer
        message = context.get("message", "")
        if not message:
            return {"sentiment": "neutral", "needs_escalation": False}
        return sentiment_analyzer.analyze(message)
    except Exception as e:
        logger.error(f"Sentiment task error: {e}")
        return {"sentiment": "neutral", "needs_escalation": False}


async def intent_task(context: Dict) -> Dict:
    """Detect intent using LLM."""
    try:
        from orchestrator import IntentDetector
        detector = IntentDetector()
        message = context.get("message", "")
        history = context.get("history", [])
        return await detector.detect(message, history)
    except Exception as e:
        logger.error(f"Intent task error: {e}")
        return {"intent": "general_query", "confidence": 0.5, "entities": {}}


async def lead_scoring_task(context: Dict) -> Dict:
    """Score the lead based on message content."""
    try:
        from services.lead_scoring import LeadScoringEngine, LeadSignal
        engine = LeadScoringEngine()
        phone = context.get("phone_number", "")
        client_id = context.get("client_id", 1)
        message = context.get("message", "").lower()

        # Record a signal based on message content
        signal = LeadSignal.MESSAGE_REPLY
        if any(w in message for w in ["price", "cost", "rate", "kitna", "fees", "charges"]):
            signal = LeadSignal.PRICE_QUERY
        elif any(w in message for w in ["book", "appointment", "schedule", "slot"]):
            signal = LeadSignal.APPOINTMENT_BOOKED
        elif any(w in message for w in ["buy", "order", "purchase", "subscribe"]):
            signal = LeadSignal.PURCHASE_MADE

        engine.record_signal(phone, signal, client_id=client_id)
        profile = engine.get_profile(phone, client_id)
        return {"score": profile.score, "tier": profile.tier.value, "qualified": profile.score >= 50}
    except Exception as e:
        logger.error(f"Lead scoring task error: {e}")
        return {"score": 0, "tier": "cold", "qualified": False}


async def knowledge_retrieval_task(context: Dict) -> List[Dict]:
    """Retrieve relevant knowledge from ChromaDB (RAG)."""
    try:
        from vector_store import search_knowledge
        message = context.get("message", "")
        client_id = context.get("client_id", 1)
        return search_knowledge(client_id, message, n_results=3)
    except Exception as e:
        logger.error(f"Knowledge retrieval error: {e}")
        return []


async def catalog_lookup_task(context: Dict) -> Optional[Dict]:
    """Look up catalog items matching the message."""
    try:
        from business_profiles import business_manager
        message = context.get("message", "").lower()
        client_id = context.get("client_id", 1)

        profile = None
        for p in business_manager.profiles.values():
            if p.client_id == int(client_id):
                profile = p
                break
        if not profile:
            return None

        items = business_manager.get_catalog(profile.id)
        if not items:
            return None

        matches = []
        for item in items:
            if item["name"].lower() in message:
                matches.append(item)
        return {"matches": matches, "all_items": items[:10]}
    except Exception as e:
        logger.error(f"Catalog lookup error: {e}")
        return None


async def conversation_summary_task(context: Dict) -> Dict:
    """Generate/update a summary of the conversation."""
    try:
        from llm_setup import get_llm
        llm = get_llm()
        message = context.get("message", "")
        history = context.get("history", [])

        if not hasattr(llm, 'invoke'):
            return {"summary": "", "needs": [], "missing_info": []}

        context_text = "\n".join([f"{'User' if h['direction'] == 'incoming' else 'Bot'}: {h['content']}" for h in history[-5:]])
        prompt = f"""You are a conversation summarizer for a WhatsApp business assistant.
Summarize what the customer wants and what info is still missing.

Previous conversation:
{context_text}

Latest message: {message}

Return ONLY valid JSON:
{{"summary": "one-line summary of what customer wants", "needs": ["list of needs"], "missing_info": ["list of missing info like name, date, time, location"]}}"""

        response = await asyncio.to_thread(llm.invoke, prompt)
        result_text = response.content if hasattr(response, 'content') else str(response)

        import re, json
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return {"summary": result_text[:200], "needs": [], "missing_info": []}
    except Exception as e:
        logger.error(f"Conversation summary error: {e}")
        return {"summary": "", "needs": [], "missing_info": []}


# ---------------------------------------------------------------------------
# Global task manager instance
# ---------------------------------------------------------------------------

task_manager = TaskManager(default_timeout=15.0)

# Register built-in tasks
task_manager.register("sentiment", sentiment_task, timeout=5.0)
task_manager.register("intent", intent_task, timeout=10.0)
task_manager.register("lead_scoring", lead_scoring_task, timeout=5.0)
task_manager.register("knowledge_retrieval", knowledge_retrieval_task, timeout=8.0)
task_manager.register("catalog_lookup", catalog_lookup_task, timeout=5.0)
task_manager.register("conversation_summary", conversation_summary_task, timeout=10.0)