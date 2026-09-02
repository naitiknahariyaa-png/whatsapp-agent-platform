"""
Manager Agent — Full Architecture Implementation
Planning → Delegation → Verification → Synthesis → Response

Implements the 5-component architecture:
1. Context Loader
2. Planner (LLM call #1)
3. Router/Delegator
4. Verifier (LLM call #2 - optional)
5. Response Composer
"""
import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from model_router import get_planning_llm, get_verification_llm, get_generation_llm

logger = logging.getLogger("manager_agent")


# =============================================================================
# DATA CONTRACTS (Section 4 of architecture)
# =============================================================================

class UrgencyLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IntentType(str, Enum):
    SALES_INQUIRY = "sales_inquiry"
    SUPPORT_QUESTION = "support_question"
    BOOKING_REQUEST = "booking_request"
    PAYMENT = "payment"
    COMPLAINT = "complaint"
    ESCALATION = "escalation"
    SMALL_TALK = "small_talk"
    ANALYTICS_REPORT = "analytics_report"
    ADVISORY_CA = "advisory_ca"
    ADVISORY_LEGAL = "advisory_legal"
    ADVISORY_STRATEGY = "advisory_strategy"
    UNKNOWN = "unknown"


@dataclass
class ManagerInput:
    """Input contract for Manager Agent (Section 4.1)."""
    client_id: int
    conversation_id: str
    message_text: str
    message_type: str = "text"  # text, voice, image
    timestamp: datetime = field(default_factory=datetime.utcnow)
    session_summary: str = ""
    entity_snapshot: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
    vertical: str = "general"
    has_open_task: bool = False
    lang: str = "en"
    phone_number: str = ""
    business_context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanStep:
    step: int
    agent: str
    task: str


@dataclass
class Plan:
    """Output from Planner (Section 4.1 schema)."""
    intent: str
    confidence: float
    plan: List[PlanStep] = field(default_factory=list)
    needs_memory: List[str] = field(default_factory=list)
    needs_rag: bool = False
    urgency: str = "low"


@dataclass
class TaskObject:
    """Manager → Specialist contract (Section 4.2)."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agent: str = "support"
    instruction: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    tools_allowed: List[str] = field(default_factory=list)
    max_iterations: int = 5


@dataclass
class SpecialistResult:
    """Specialist → Manager contract (Section 4.3)."""
    task_id: str
    status: str  # success, error, needs_escalation
    response_text: Optional[str] = None
    tools_called: List[str] = field(default_factory=list)
    confidence: float = 0.0
    entity_updates: Dict[str, Any] = field(default_factory=dict)
    citations: List[str] = field(default_factory=list)


@dataclass
class VerdictOutput:
    """Verifier output (Section 4.4)."""
    approved: bool
    reason: Optional[str] = None
    suggested_fix: Optional[str] = None


# =============================================================================
# ROUTING TABLE (Section 6)
# =============================================================================

ROUTING_TABLE = {
    IntentType.SALES_INQUIRY: {
        "primary": "sales",
        "fallback": "support",
        "verify": False,
        "description": "Price/plan questions, product inquiries",
    },
    IntentType.SUPPORT_QUESTION: {
        "primary": "support",
        "fallback": "support",
        "verify": False,
        "description": "Help, problems, how-to questions",
    },
    IntentType.BOOKING_REQUEST: {
        "primary": "concierge",
        "fallback": "support",
        "verify": False,
        "description": "Appointments, scheduling, calendar",
    },
    IntentType.PAYMENT: {
        "primary": "billing",
        "fallback": "escalation",
        "verify": True,
        "description": "Payments, invoices, billing — always verify",
    },
    IntentType.COMPLAINT: {
        "primary": "escalation",
        "fallback": "escalation",
        "verify": False,
        "description": "Sentiment-triggered, skip specialist",
    },
    IntentType.SMALL_TALK: {
        "primary": "sales",
        "fallback": "sales",
        "verify": False,
        "description": "Greetings, chit-chat — cheap, no tools",
    },
    IntentType.UNKNOWN: {
        "primary": "escalation",
        "fallback": "escalation",
        "verify": False,
        "description": "Never guess into Billing",
    },
    IntentType.ADVISORY_CA: {
        "primary": "ca_advisor",
        "fallback": "escalation",
        "verify": True,
        "description": "Tax, compliance, financial advice",
    },
    IntentType.ADVISORY_LEGAL: {
        "primary": "legal_advisor",
        "fallback": "escalation",
        "verify": True,
        "description": "Legal, contracts, compliance",
    },
    IntentType.ADVISORY_STRATEGY: {
        "primary": "business_strategist",
        "fallback": "escalation",
        "verify": False,
        "description": "Business growth, marketing, operations",
    },
}


# =============================================================================
# 1. CONTEXT LOADER (Section 3.1)
# =============================================================================

class ContextLoader:
    """
    Pulls exactly what's needed — never full history, never full entity table.
    The #1 place token bloat and latency creep in.
    """

    def __init__(self):
        self._history_window = 10  # Last N messages
        self._summary_turns = 20   # Summarize older than this

    async def load(self, manager_input: ManagerInput) -> Dict[str, Any]:
        """Build the Manager Input context object."""
        context = {
            "client_id": manager_input.client_id,
            "conversation_id": manager_input.conversation_id,
            "message": manager_input.message_text,
            "message_type": manager_input.message_type,
            "timestamp": manager_input.timestamp.isoformat(),
            "vertical": manager_input.vertical,
            "lang": manager_input.lang,
            "phone_number": manager_input.phone_number,
        }

        # Rolling summary (already provided or compute)
        if not manager_input.session_summary:
            context["session_summary"] = await self._summarize_history(manager_input.history)
        else:
            context["session_summary"] = manager_input.session_summary

        # Entity snapshot (only relevant fields for current intent)
        context["entity_snapshot"] = self._filter_relevant_entities(
            manager_input.entity_snapshot, manager_input.message_text
        )

        # Open task flag
        context["has_open_task"] = manager_input.has_open_task

        # Recent history (last N turns only)
        recent = manager_input.history[-self._history_window:] if manager_input.history else []
        context["recent_turns"] = [
            {"role": h.get("direction", "incoming"), "content": h.get("content", "")[:200]}
            for h in recent
        ]

        return context

    async def _summarize_history(self, history: List[Dict]) -> str:
        """Summarize older conversation turns."""
        if not history:
            return "New conversation — no history yet."

        if len(history) <= self._summary_turns:
            # Short enough to include directly
            turns = []
            for h in history[-10:]:
                role = "User" if h.get("direction") == "incoming" else "Bot"
                turns.append(f"{role}: {h.get('content', '')[:150]}")
            return "\n".join(turns)

        # Summarize older turns
        older = history[:-self._history_window]
        topics = set()
        for msg in older:
            content = msg.get("content", "").lower()
            if any(kw in content for kw in ["budget", "price", "cost"]):
                topics.add("budget")
            if any(kw in content for kw in ["appointment", "book", "schedule"]):
                topics.add("appointment")
            if any(kw in content for kw in ["document", "upload", "send"]):
                topics.add("documents")
            if any(kw in content for kw in ["question", "help", "how", "what"]):
                topics.add("questions")

        summary_parts = []
        if topics:
            summary_parts.append(f"Topics discussed: {', '.join(sorted(topics))}")
        for msg in reversed(older):
            if msg.get("direction") == "incoming":
                summary_parts.append(f"Last user message: {msg.get('content', '')[:100]}")
                break

        return " | ".join(summary_parts) if summary_parts else "Ongoing conversation."

    def _filter_relevant_entities(self, entities: Dict[str, Any], message: str) -> Dict[str, Any]:
        """Only include entity fields relevant to the current message."""
        msg_lower = message.lower()

        # Define relevance per topic
        relevance_map = {
            "budget": ["budget", "budget_min", "budget_max"],
            "time": ["preferred_time", "timezone", "preferred_date"],
            "location": ["location", "city", "state", "pincode"],
            "contact": ["email", "phone", "alternate_phone"],
            "name": ["name", "person_name"],
            "booking": ["preferred_date", "preferred_time", "timezone"],
        }

        relevant_keys = set()
        for topic, keys in relevance_map.items():
            if any(kw in msg_lower for kw in topic.split()):
                relevant_keys.update(keys)

        # Always include name if known
        if "name" in entities:
            relevant_keys.add("name")

        if not relevant_keys:
            # Return only non-sensitive, high-level fields
            return {k: v for k, v in entities.items() if k in ("name", "company_name")}

        return {k: v for k, v in entities.items() if k in relevant_keys}


# =============================================================================
# 2. PLANNER (Section 3.2)
# =============================================================================

SYSTEM_PROMPT_TEMPLATE = """You are the Manager Agent for {business_name}, a {business_vertical} business.
You do NOT answer the customer directly. Your only job is to analyze the
message and output a structured plan.

Available specialists:
- sales: pricing, product info, quotes, payment links
- support: FAQs, how-to, troubleshooting, knowledge base
- concierge: appointments, scheduling, reminders
- escalation: human handoff for complaints or complex issues

Rules:
- If you are not confident which specialist applies, choose "support" as
  the safe default, or "escalation" if the message suggests frustration,
  a complaint, or a topic outside normal business scope.
- Never route directly to "escalation" unless the user explicitly asks for
  a human or expresses frustration/complaint.
- If the user's message indicates urgency, distress, or a request to speak
  to a human, set urgency to "high".
- The plan is almost always a single step.

Conversation summary: {session_summary}
Relevant known facts: {entity_snapshot}
Latest message: {message_text}

Output ONLY the JSON plan. No prose, no explanation.
"""


class Planner:
    """
    LLM-based planner that outputs structured routing decisions.
    Uses function-calling / JSON mode, never free-text parsing.
    """

    def __init__(self):
        self.llm = get_planning_llm()
        self._confidence_threshold_low = 0.4
        self._confidence_threshold_high = 0.7

    async def plan(self, manager_input: ManagerInput, business_name: str = "Our Business") -> Plan:
        """
        Generate a routing plan from the Manager Input.

        Returns:
            Plan with intent, confidence, steps, and metadata
        """
        # Build context
        loader = ContextLoader()
        context = await loader.load(manager_input)

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            business_name=business_name,
            business_vertical=manager_input.vertical,
            session_summary=context.get("session_summary", ""),
            entity_snapshot=json.dumps(context.get("entity_snapshot", {})),
            message_text=manager_input.message_text,
        )

        # Inject real business facts so routing/answers reflect the actual business
        biz_ctx = getattr(manager_input, "business_context", None) or {}
        if biz_ctx:
            prompt += "\n\n### BUSINESS CONTEXT (facts only — do NOT invent)\n"
            prompt += json.dumps(biz_ctx, ensure_ascii=False, default=str)
            prompt += (
                "\nWhen passing tasks to specialists, include the relevant business "
                "facts (name, menu/items with prices, hours, policies) in the task so "
                "the customer receives business-specific answers.\n"
            )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"User message: {manager_input.message_text}"},
        ]

        try:
            if self.llm is not None and hasattr(self.llm, "ainvoke"):
                response = await self.llm.ainvoke(messages)
                content = response.content if hasattr(response, "content") else str(response)
            else:
                # Fallback: use generation LLM
                gen_llm = get_generation_llm()
                response = await gen_llm.ainvoke(messages)
                content = response.content if hasattr(response, "content") else str(response)

            plan_data = self._parse_plan(content)
            if plan_data:
                return plan_data

        except Exception as e:
            logger.warning(f"Planner LLM call failed: {e}")

        # Hardcoded fallback if planner fails
        return self._keyword_fallback(manager_input.message_text)

    # specialist-name -> intent mapping (LLMs often answer in this schema)
    _SPECIALIST_TO_INTENT = {
        "concierge": "booking_request",
        "sales": "sales_inquiry",
        "salesmaster": "sales_inquiry",
        "support": "support_question",
        "billing": "payment",
        "escalation": "escalation",
        "marketing": "sales_inquiry",
        "analytics": "analytics_report",
    }

    def _parse_plan(self, text: str) -> Optional[Plan]:
        """Parse JSON plan from LLM response.

        Tolerates two schemas:
          A) {"intent": "booking_request", "confidence": 0.9, "plan": [{"agent": "concierge", "task": ...}]}
          B) {"specialist": "concierge", "urgency": "normal", "reasoning": ...,
              "steps": [{"action": "route_to", "target": "concierge", "context": ...}]}
        """
        try:
            # Try to find JSON in the response
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if not json_match:
                return None

            data = json.loads(json_match.group(0))

            # Validate required fields
            urgency = data.get("urgency", "low")
            needs_memory = data.get("needs_memory", [])
            needs_rag = data.get("needs_rag", False)

            raw_steps = data.get("plan") or data.get("steps") or []
            steps: List[PlanStep] = []
            for i, s in enumerate(raw_steps):
                if not isinstance(s, dict):
                    continue
                agent_name = s.get("agent") or s.get("target") or s.get("specialist") or "support"
                task_txt = s.get("task") or s.get("context") or s.get("action") or ""
                steps.append(PlanStep(step=s.get("step", i + 1), agent=str(agent_name).lower(),
                                      task=str(task_txt)))

            intent = data.get("intent")
            if not intent:
                # Schema B: infer intent from the specialist name
                specialist = str(data.get("specialist") or
                                 (steps[0].agent if steps else "")).lower()
                intent = self._SPECIALIST_TO_INTENT.get(specialist, "unknown")

            # Schema B is an explicit routing decision -> treat as confident
            default_conf = 0.85 if data.get("specialist") else 0.5
            confidence = float(data.get("confidence", default_conf))

            # Normalize intent
            try:
                intent_enum = IntentType(intent)
            except ValueError:
                intent_enum = IntentType.UNKNOWN

            if intent_enum == IntentType.UNKNOWN and not steps:
                return None  # nothing usable — let caller fall back

            if not steps:
                # Intent known but no steps: route to the obvious specialist
                default_agent = {
                    "booking_request": "concierge", "sales_inquiry": "sales",
                    "support_question": "support", "payment": "billing",
                    "escalation": "escalation", "complaint": "escalation",
                }.get(intent_enum.value, "support")
                steps = [PlanStep(step=1, agent=default_agent, task="Handle the customer request")]

            return Plan(
                intent=intent_enum.value,
                confidence=confidence,
                plan=steps,
                needs_memory=needs_memory,
                needs_rag=needs_rag,
                urgency=urgency,
            )

        except Exception as e:
            logger.warning(f"Plan parsing failed: {e}")
            return None

    def _keyword_fallback(self, message: str) -> Plan:
        """Keyword-based fallback when LLM fails."""
        msg = message.lower()

        # Check for escalation signals first
        escalation_keywords = ["human", "agent", "real person", "talk to human", "complaint", "unhappy", "disappointed"]
        if any(kw in msg for kw in escalation_keywords):
            return Plan(
                intent=IntentType.ESCALATION.value,
                confidence=0.9,
                plan=[PlanStep(step=1, agent="escalation", task="User requested human or expressed complaint")],
                urgency="high",
            )

        # Check for sales signals
        sales_keywords = ["price", "cost", "kitna", "charges", "fees", "buy", "purchase", "interested", "plan", "package"]
        if any(kw in msg for kw in sales_keywords):
            return Plan(
                intent=IntentType.SALES_INQUIRY.value,
                confidence=0.8,
                plan=[PlanStep(step=1, agent="sales", task="Answer pricing/product question")],
                urgency="low",
            )

        # Check for booking signals
        booking_keywords = ["book", "schedule", "appointment", "meeting", "slot", "visit", "tomorrow", "today"]
        if any(kw in msg for kw in booking_keywords):
            return Plan(
                intent=IntentType.BOOKING_REQUEST.value,
                confidence=0.85,
                plan=[PlanStep(step=1, agent="concierge", task="Handle booking/scheduling request")],
                urgency="low",
            )

        # Check for payment signals
        payment_keywords = ["pay", "payment", "razorpay", "upi", "invoice", "receipt"]
        if any(kw in msg for kw in payment_keywords):
            return Plan(
                intent=IntentType.PAYMENT.value,
                confidence=0.85,
                plan=[PlanStep(step=1, agent="sales", task="Handle payment/billing request")],
                urgency="high",
            )

        # Check for reporting/analytics signals (owner asking for numbers)
        report_keywords = ["report", "analytics", "stats", "statistics",
                           "how many leads", "funnel", "this week", "conversion"]
        if any(kw in msg for kw in report_keywords):
            return Plan(
                intent=IntentType.ANALYTICS_REPORT.value,
                confidence=0.75,
                plan=[PlanStep(step=1, agent="analytics",
                               task="Compile a real-numbers business snapshot")],
                urgency="low",
            )

        # Check for support signals
        support_keywords = ["help", "problem", "issue", "error", "not working", "how to", "question"]
        if any(kw in msg for kw in support_keywords):
            return Plan(
                intent=IntentType.SUPPORT_QUESTION.value,
                confidence=0.8,
                plan=[PlanStep(step=1, agent="support", task="Answer support question from knowledge base")],
                urgency="low",
            )

        # Default: small talk / unknown → support as safe default
        return Plan(
            intent=IntentType.SMALL_TALK.value,
            confidence=0.5,
            plan=[PlanStep(step=1, agent="support", task="Handle general query")],
            urgency="low",
        )


# =============================================================================
# 3. ROUTER / DELEGATOR (Section 3.3)
# =============================================================================

class Router:
    """
    Deterministic router — NOT an LLM call.
    Takes the Planner's intent + plan and routes to the right specialist.
    """

    def __init__(self):
        self._specialists: Dict[str, Any] = {}
        # Tool-loop specialists (book/pRAG) make 3-5 LLM calls per turn; on a
        # hosted LLM that legitimately takes 30-90s. 15s guaranteed timeouts
        # -> retry -> escalate on every booking. Make it configurable & sane.
        self._default_timeout = float(os.getenv("SPECIALIST_TIMEOUT", "120"))

    def register(self, name: str, agent: Any):
        """Register a specialist agent."""
        self._specialists[name] = agent

    def get_specialist(self, name: str) -> Optional[Any]:
        """Get a registered specialist by name."""
        return self._specialists.get(name)

    def get_route_config(self, intent: str) -> Dict[str, Any]:
        """Get routing config for an intent."""
        try:
            intent_enum = IntentType(intent)
            return ROUTING_TABLE.get(intent_enum, ROUTING_TABLE[IntentType.UNKNOWN])
        except ValueError:
            return ROUTING_TABLE[IntentType.UNKNOWN]

    def build_task(self, plan: Plan, manager_input: ManagerInput, agent_name: str) -> TaskObject:
        """Build a TaskObject with only the context this specialist needs."""

        # Determine allowed tools based on agent
        tools_map = {
            "sales": ["lookup_product", "generate_payment_link", "check_inventory"],
            "support": ["search_knowledge_base", "lookup_faq"],
            "concierge": ["check_calendar", "book_appointment", "check_availability"],
            "escalation": ["request_handoff", "notify_owner"],
        }

        instruction = plan.plan[0].task if plan.plan else "Handle this request"

        return TaskObject(
            agent=agent_name,
            instruction=instruction,
            context={
                "message": manager_input.message_text,
                "phone_number": manager_input.phone_number,
                "client_id": manager_input.client_id,
                "vertical": manager_input.vertical,
                "lang": manager_input.lang,
                "entity_snapshot": manager_input.entity_snapshot,
                "session_summary": manager_input.session_summary,
                "history": manager_input.history[-6:] if manager_input.history else [],
                "needs_rag": plan.needs_rag,
                "business_context": getattr(manager_input, "business_context", {}) or {},
            },
            tools_allowed=tools_map.get(agent_name, []),
        )

    async def delegate(self, task: TaskObject) -> SpecialistResult:
        """
        Execute a task with timeout and return the result.
        """
        specialist = self.get_specialist(task.agent)
        if specialist is None:
            # Try fallback
            specialist = self.get_specialist("support")

        if specialist is None:
            return SpecialistResult(
                task_id=task.task_id,
                status="error",
                response_text="No specialist available for this request.",
                confidence=0.0,
            )

        try:
            # Execute with timeout
            result_text = await asyncio.wait_for(
                specialist.run(task.instruction, context=task.context),
                timeout=self._default_timeout,
            )
            return SpecialistResult(
                task_id=task.task_id,
                status="success",
                response_text=result_text,
                confidence=0.8,  # Default confidence; specialist can override
            )

        except asyncio.TimeoutError:
            logger.warning(f"Specialist {task.agent} timed out after {self._default_timeout}s")
            return SpecialistResult(
                task_id=task.task_id,
                status="error",
                response_text=None,
                confidence=0.0,
            )

        except Exception as e:
            logger.error(f"Specialist {task.agent} failed: {e}")
            return SpecialistResult(
                task_id=task.task_id,
                status="error",
                response_text=None,
                confidence=0.0,
            )


# =============================================================================
# 4. VERIFIER (Section 3.4)
# =============================================================================

VERIFICATION_PROMPT = """You are a verification agent. Check if the specialist's response accurately addresses the user's original request.

User Input: {original_input}
Task: {task}
Response: {response}

Check:
1. Does the response address the original intent? (catches wrong specialist answering)
2. Does it contradict known facts in entity memory? (e.g., quoting different price)
3. Does it violate any hard constraint? (no medical/legal advice, no discount promises above X%)

Respond ONLY in JSON: {{"approved": true/false, "reason": "...", "suggested_fix": "..."}}
"""


class Verifier:
    """
    Optional verification gate for high-stakes responses.
    Skips for simple support/RAG answers to save cost.
    """

    def __init__(self):
        self.llm = get_verification_llm()

    async def verify(
        self,
        original_input: str,
        task: str,
        result: SpecialistResult,
        entity_snapshot: Dict[str, Any] = None,
    ) -> VerdictOutput:
        """
        Verify a specialist result against the original request.

        Returns:
            VerdictOutput with approved flag and optional feedback
        """
        if not result.response_text:
            return VerdictOutput(
                approved=False,
                reason="Empty response from specialist",
                suggested_fix="Retry with clearer instruction",
            )

        # Skip verification for non-critical intents
        if result.confidence >= 0.9 and result.status == "success":
            return VerdictOutput(approved=True)

        try:
            if self.llm is None:
                # Use generation LLM as fallback
                self.llm = get_generation_llm()

            prompt = VERIFICATION_PROMPT.format(
                original_input=original_input,
                task=task,
                response=result.response_text[:2000],  # Cap length
            )

            messages = [{"role": "user", "content": prompt}]
            response = await self.llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)

            # Parse JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return VerdictOutput(
                    approved=bool(data.get("approved", True)),
                    reason=data.get("reason"),
                    suggested_fix=data.get("suggested_fix"),
                )

        except Exception as e:
            logger.warning(f"Verification failed: {e}")

        # Default: approve on verification failure
        return VerdictOutput(approved=True)


# =============================================================================
# 5. RESPONSE COMPOSER (Section 3.5)
# =============================================================================

class ResponseComposer:
    """
    Formats specialist output for WhatsApp delivery.
    - Splits long messages at sentence boundaries
    - Injects typing-indicator delay
    - Attaches media (payment links, calendar invites)
    - Writes turn to session memory
    """

    def __init__(self):
        self._max_chunk_len = 4096  # WhatsApp limit
        self._typing_delay = (1.5, 3.0)  # Min/max seconds

    async def compose(self, result: SpecialistResult, manager_input: ManagerInput) -> str:
        """
        Format the final response for WhatsApp.

        Args:
            result: Specialist result
            manager_input: Original manager input

        Returns:
            Formatted response string
        """
        if not result.response_text:
            return "I'm sorry, I couldn't process that request. Let me connect you with a human agent."

        text = result.response_text.strip()

        # Part H.5 — never let a cut-off LLM reply reach the customer.  If the
        # specialist output looks truncated, request one continuation slice.
        try:
            from truncation_guard import auto_continue, looks_truncated
            if looks_truncated(text):
                from model_router import get_generation_llm
                llm = get_generation_llm()

                async def _continue_only():
                    try:
                        res = await llm.ainvoke(
                            "Continue your previous reply exactly where you stopped. Do not repeat.")
                        return getattr(res, "content", None) or ""
                    except Exception:
                        return ""

                text = await auto_continue(
                    text,
                    _continue_only,
                    max_chars=self._max_chunk_len,
                    max_continuations=1,
                )
        except Exception:
            pass

        # Apply spell check if available
        try:
            from utils.integrations import spellcheck_business_reply
            text = await spellcheck_business_reply(text, manager_input.lang)
        except Exception:
            pass

        # Split long messages
        chunks = self._split_message(text)

        # For multi-part messages, join with continuation marker
        if len(chunks) > 1:
            return "\n\n".join(chunks)

        return chunks[0] if chunks else text

    def _split_message(self, text: str) -> List[str]:
        """
        Split long messages at sentence boundaries.
        """
        if len(text) <= self._max_chunk_len:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= self._max_chunk_len:
                chunks.append(remaining)
                break

            # Find last sentence ending within last 20% of chunk
            search_start = max(0, self._max_chunk_len - int(self._max_chunk_len * 0.2))
            split_at = self._max_chunk_len

            for i in range(self._max_chunk_len - 1, search_start - 1, -1):
                if remaining[i] in ".!?" and (i + 1 == len(remaining) or remaining[i + 1] in " \n"):
                    split_at = i + 1
                    break

            chunk = remaining[:split_at].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[split_at:].strip()

        return chunks

    async def attach_media(self, text: str, media_url: str = None, media_type: str = None) -> str:
        """Attach media (payment link, calendar invite) to response."""
        if media_url:
            if media_type == "payment":
                return f"{text}\n\n💳 Payment Link: {media_url}"
            elif media_type == "calendar":
                return f"{text}\n\n📅 Calendar invite sent separately."
            else:
                return f"{text}\n\n{media_url}"
        return text


# =============================================================================
# 6. SPECIALIST REGISTRY
# =============================================================================

class SpecialistRegistry:
    """Registry of all specialist agents."""

    def __init__(self):
        self._agents: Dict[str, Any] = {}

    def register(self, name: str, agent: Any):
        """Register a specialist agent."""
        self._agents[name] = agent

    def get(self, name: str) -> Optional[Any]:
        """Get a specialist by name."""
        return self._agents.get(name)

    def get_or_fallback(self, name: str, fallback: str = "support") -> Any:
        """Get specialist or fallback to support."""
        return self._agents.get(name, self._agents.get(fallback))

    @property
    def names(self) -> List[str]:
        """List all registered specialist names."""
        return list(self._agents.keys())


# =============================================================================
# 7. MAIN MANAGER AGENT (Section 3 - Orchestrator)
# =============================================================================


class ManagerAgent(BaseAgent):
    """
    Full Manager Agent implementation.
    Input → Plan → Delegate → Verify → Respond
    """

    def __init__(self, business_name: str = "Our Business"):
        system_prompt = (
            "You are the Manager Agent. Your sole responsibility is orchestration. "
            "You do NOT answer the customer directly. "
            "Your only job is to analyze the message and output a structured plan.\n\n"
            "Available specialists: sales, support, concierge, escalation.\n\n"
            "Rules:\n"
            "1. NEVER answer domain questions yourself. Delegate to specialists.\n"
            "2. If you are not confident which specialist applies, choose 'support' as the safe default.\n"
            "3. If the user expresses frustration or asks for a human, choose 'escalation'.\n"
            "4. Output ONLY JSON. No prose."
        )
        super().__init__(
            name="Manager",
            role="Orchestrator",
            system_prompt=system_prompt,
            tools=[],
        )

        self.business_name = business_name
        self.planner = Planner()
        self.router = Router()
        self.verifier = Verifier()
        self.composer = ResponseComposer()
        self.registry = SpecialistRegistry()

        # Register default specialists
        self._register_defaults()

    def _register_defaults(self):
        """Register default specialist agents."""
        specialist_modules = [
            ("sales", "agents.sales", "SalesAgent"),
            ("support", "agents.support", "SupportAgent"),
            ("concierge", "agents.concierge", "ConciergeAgent"),
            ("billing", "agents.billing", "BillingAgent"),
            ("marketing", "agents.marketing", "MarketingAgent"),
            ("content", "agents.content", "ContentAgent"),
            ("onboarding", "agents.onboarding_agent", "OnboardingAgent"),
            ("retention", "agents.retention", "RetentionAgent"),
            ("hr", "agents.hr", "HRAgent"),
            ("legal", "agents.legal", "LegalAgent"),
            ("devops", "agents.devops", "DevOpsAgent"),
            ("qa", "agents.qa_agent", "QAAgent"),
            ("analytics", "agents.analytics", "AnalyticsAgent"),
            ("escalation", "agents.escalation", "EscalationAgent"),
            ("ca_advisor", "agents.advisory", "CAAgent"),
            ("legal_advisor", "agents.advisory", "LegalAdvisorAgent"),
            ("business_strategist", "agents.advisory", "BusinessStrategistAgent"),
        ]

        for name, module_path, class_name in specialist_modules:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                agent_cls = getattr(mod, class_name)
                self.registry.register(name, agent_cls())
                logger.info(f"Registered specialist: {name}")
            except Exception as e:
                logger.warning(f"Could not register {name}: {e}")

        # Register router
        for name in self.registry.names:
            self.router.register(name, self.registry.get(name))

    async def handle(self, manager_input: ManagerInput) -> str:
        """
        Main entry point: process a ManagerInput through the full pipeline.

        Args:
            manager_input: Structured input with message, context, history

        Returns:
            Final response string for the user
        """
        # Step 1: Plan
        plan = await self.planner.plan(manager_input, self.business_name)
        logger.info(
            "[Manager] intent=%s confidence=%.2f urgency=%s",
            plan.intent, plan.confidence, plan.urgency,
        )

        # Step 2: Confidence check
        if plan.confidence < self.planner._confidence_threshold_low:
            logger.info("[Manager] Low confidence (%.2f), escalating", plan.confidence)
            return await self._escalate(manager_input, reason=f"Low routing confidence ({plan.confidence:.2f})")

        # Determine agent: use plan's agent if confidence is high, else safe default
        if plan.confidence >= self.planner._confidence_threshold_high and plan.plan:
            agent_name = plan.plan[0].agent
        else:
            route_config = self.router.get_route_config(plan.intent)
            agent_name = route_config.get("fallback", "support")

        # Check for escalation intent
        if plan.intent == IntentType.ESCALATION.value or plan.urgency == UrgencyLevel.HIGH.value:
            if self._is_frustration_signal(manager_input.message_text):
                return await self._escalate(manager_input, reason="User frustration detected")

        # Step 3: Delegate
        task = self.router.build_task(plan, manager_input, agent_name)
        logger.info("[Manager] Delegating to %s: %s", agent_name, task.instruction[:100])

        result = await self.router.delegate(task)

        # Step 4: Handle specialist result
        if result.status == "needs_escalation":
            return await self._escalate(manager_input, reason="Specialist requested escalation")

        if result.status == "error":
            # Retry once
            logger.info("[Manager] Specialist failed, retrying...")
            result = await self._retry_specialist(task, result)
            if result.status != "success":
                return await self._escalate(manager_input, reason="Specialist failed after retry")

        # Step 5: Verification (conditional)
        route_config = self.router.get_route_config(plan.intent)
        if route_config.get("verify", False) or result.confidence < 0.7:
            verdict = await self.verifier.verify(
                original_input=manager_input.message_text,
                task=task.instruction,
                result=result,
                entity_snapshot=manager_input.entity_snapshot,
            )
            if not verdict.approved:
                logger.info("[Manager] Verification failed: %s", verdict.reason)
                # Retry with fix
                result = await self._retry_specialist(task, result, fix=verdict.suggested_fix)
                if result.status != "success":
                    return await self._escalate(manager_input, reason="Verification failed after retry")

        # Step 6: Compose response
        response = await self.composer.compose(result, manager_input)

        # Track analytics
        try:
            from utils.analytics import track_event
            await track_event("manager_routed", {
                "intent": plan.intent,
                "agent": agent_name,
                "confidence": plan.confidence,
                "status": result.status,
            }, client_id=manager_input.client_id)
        except Exception:
            pass

        return response

    async def _retry_specialist(
        self, task: TaskObject, previous_result: SpecialistResult, fix: str = None
    ) -> SpecialistResult:
        """Retry a specialist with modified instruction."""
        retry_task = TaskObject(
            task_id=task.task_id,
            agent=task.agent,
            instruction=f"{task.instruction}. Previous attempt failed: {previous_result.response_text}. {fix or 'Try a different approach.'}",
            context=task.context,
            tools_allowed=task.tools_allowed,
        )
        return await self.router.delegate(retry_task)

    async def _escalate(self, manager_input: ManagerInput, reason: str) -> str:
        """
        Route to human escalation.
        """
        logger.info("[Manager] Escalating: %s", reason)

        # Notify owner if possible
        try:
            from utils.leads import notify_owner
            await notify_owner(
                message=f"Escalation needed for {manager_input.phone_number}: {reason}",
                channel="whatsapp",
                priority="high",
                client_id=manager_input.client_id,
            )
        except Exception:
            pass

        # Try handoff
        try:
            from handoff import request_handoff
            await request_handoff(manager_input.phone_number, reason, 0.0)
        except Exception:
            pass

        return "I've escalated this to a human agent who will get back to you shortly. Thank you for your patience! 🙏"

    def _is_frustration_signal(self, message: str) -> bool:
        """Detect frustration in user message."""
        try:
            from utils.leads import classify_sentiment
            sentiment = classify_sentiment(message)
            return sentiment.value in ("negative", "frustrated")
        except Exception:
            # Fallback keyword check
            frustration_keywords = ["frustrated", "annoyed", "angry", "worst", "terrible", "useless", "ridiculous", "unacceptable"]
            return any(kw in message.lower() for kw in frustration_keywords)

    # Backwards-compatible run method
    async def run(self, user_input: str, context: Dict[str, Any] = None) -> str:
        """Legacy interface — wraps handle()."""
        if context is None:
            context = {}

        manager_input = ManagerInput(
            client_id=context.get("client_id", 1),
            conversation_id=context.get("conversation_id", str(uuid.uuid4())[:8]),
            message_text=user_input,
            vertical=context.get("vertical", "general"),
            lang=context.get("lang", "en"),
            phone_number=context.get("phone_number", ""),
            entity_snapshot=context.get("entity_snapshot", {}),
            history=context.get("history", []),
            has_open_task=context.get("has_open_task", False),
        )
        return await self.handle(manager_input)


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================

_manager_agent: Optional[ManagerAgent] = None


def get_manager_agent(business_name: str = "Our Business") -> ManagerAgent:
    """Get or create the singleton Manager Agent."""
    global _manager_agent
    if _manager_agent is None:
        _manager_agent = ManagerAgent(business_name=business_name)
    return _manager_agent
