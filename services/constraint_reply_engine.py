"""
Constraint-Aware Reply Engine
Extracts constraints from messy mixed-language messages and generates
human-like, constraint-aware replies using the owner's actual catalog.

This is the reasoning pipeline from the spec:
1. Language + tone detection
2. Constraint extraction (small LLM call)
3. Constraint-to-query translation
4. Catalog ranking
5. Fallback handling (relax least-critical constraint)
6. Response composition (mirror tone, 1-2 options)
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from model_router import get_classification_llm

logger = logging.getLogger("constraint_engine")


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------

@dataclass
class ExtractedConstraints:
    language_detected: str = "en"
    intent: str = "product_recommendation"
    budget_max: Optional[float] = None
    budget_min: Optional[float] = None
    time_sensitivity: str = "low"  # low, medium, high
    prep_time_max_minutes: Optional[int] = None
    category: Optional[str] = None
    quantity: Optional[int] = None
    dietary_flags: List[str] = field(default_factory=list)
    tone_needed: str = "casual"
    currency_assumed: str = "INR"
    location: Optional[str] = None
    raw_constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CatalogMatch:
    item_id: int
    name: str
    price: float
    prep_time_minutes: int
    prep_time_tier: str
    category: str
    tags: List[str]
    available: bool
    match_score: float
    constraint_satisfied: Dict[str, bool]


# ---------------------------------------------------------------------------
# 1. Language + tone detection
# ---------------------------------------------------------------------------

LANGUAGE_INDICATORS = {
    "hi_en": ["mujhe", "mera", "kya", "hai", "nahi", "bhi", "aur", "per", "lekin", "par", "kitna", "kuch", "batao", "do", "chahiye", "hai", "hoga"],
    "hi": ["मुझे", "मेरा", "क्या", "है", "नहीं", "भी", "और", "पर", "कितना", "कुछ", "बताओ", "दो", "चाहिए"],
    "en": ["i want", "i need", "please", "can you", "how much", "what is", "tell me", "give me"],
}

VOICE_INDICATORS = {
    "formal": ["sir", "madam", "kindly", "please", "regards", "thank you", "appreciate"],
    "casual": ["bhai", "bhaiya", "didi", "bhai", "yaar", "bro", "dude", "acha", "theek"],
    "playful": ["haha", "lol", "omg", "wow", "super", "best", "love"],
}


def detect_language_and_tone(message: str) -> Tuple[str, str]:
    """
    Detect language register and tone from message.
    Returns (language, tone).
    """
    msg_lower = message.lower()

    # Detect language
    hi_en_score = sum(1 for kw in LANGUAGE_INDICATORS["hi_en"] if kw in msg_lower)
    hi_score = sum(1 for kw in LANGUAGE_INDICATORS["hi"] if kw in msg_lower)
    en_score = sum(1 for kw in LANGUAGE_INDICATORS["en"] if kw in msg_lower)

    if hi_en_score >= 2 and en_score >= 1:
        language = "hi_en"
    elif hi_score >= 2:
        language = "hi"
    elif en_score >= 2:
        language = "en"
    elif hi_en_score >= 1:
        language = "hi_en"
    else:
        language = "en"

    # Detect tone
    formal_score = sum(1 for kw in VOICE_INDICATORS["formal"] if kw in msg_lower)
    casual_score = sum(1 for kw in VOICE_INDICATORS["casual"] if kw in msg_lower)
    playful_score = sum(1 for kw in VOICE_INDICATORS["playful"] if kw in msg_lower)

    if casual_score >= playful_score and casual_score >= formal_score:
        tone = "casual"
    elif formal_score >= casual_score and formal_score >= playful_score:
        tone = "formal"
    elif playful_score >= casual_score and playful_score >= formal_score:
        tone = "playful"
    else:
        tone = "casual"  # default for Indian business context

    return language, tone


# ---------------------------------------------------------------------------
# 2. Constraint extraction (small LLM call)
# ---------------------------------------------------------------------------

CONSTRAINT_EXTRACTION_PROMPT = """You are a constraint extraction engine for a WhatsApp business assistant.
Extract ALL constraints from the user's message. Return ONLY valid JSON.

Extract these fields if present:
- budget_max: number (max amount user can spend, e.g. 250)
- budget_min: number (min amount if mentioned)
- time_sensitivity: "low", "medium", or "high" (if user mentions urgency, jaldi, fast, quick, time kam hai)
- prep_time_max_minutes: number (max minutes user can wait)
- category: string (food, service, product, etc. — infer from context)
- quantity: number (how many items they want)
- dietary_flags: array of strings (veg, non-veg, jain, etc.)
- intent: string (product_recommendation, booking, support, complaint, pricing_query, general)
- location: string (if mentioned)
- currency_assumed: string (default "INR")

User message: {message}
Detected language: {language}

Return ONLY valid JSON like:
{{"budget_max": 250, "time_sensitivity": "high", "prep_time_max_minutes": 15, "category": "food", "intent": "product_recommendation", "tone_needed": "casual"}}
If no constraints found, return: {{}}
"""


async def extract_constraints(message: str, language: str = "auto") -> ExtractedConstraints:
    """
    Extract structured constraints from a messy natural language message.
    Uses a small LLM call for extraction.
    """
    detected_lang, detected_tone = detect_language_and_tone(message)

    if language == "auto":
        language = detected_lang

    try:
        llm = get_classification_llm()
        if llm is None:
            return ExtractedConstraints(language_detected=language, tone_needed=detected_tone)

        prompt = CONSTRAINT_EXTRACTION_PROMPT.format(
            message=message,
            language=language,
        )

        messages = [{"role": "user", "content": prompt}]
        if hasattr(llm, "ainvoke"):
            response = await llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
        else:
            response = await llm.generate(messages)
            content = response.get("content", "")

        # Parse JSON
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            return ExtractedConstraints(
                language_detected=language,
                intent=data.get("intent", "product_recommendation"),
                budget_max=float(data["budget_max"]) if data.get("budget_max") else None,
                budget_min=float(data["budget_min"]) if data.get("budget_min") else None,
                time_sensitivity=data.get("time_sensitivity", "low"),
                prep_time_max_minutes=int(data["prep_time_max_minutes"]) if data.get("prep_time_max_minutes") else None,
                category=data.get("category"),
                quantity=int(data["quantity"]) if data.get("quantity") else None,
                dietary_flags=data.get("dietary_flags", []),
                tone_needed=data.get("tone_needed", detected_tone),
                currency_assumed=data.get("currency_assumed", "INR"),
                location=data.get("location"),
                raw_constraints=data,
            )

    except Exception as e:
        logger.warning(f"Constraint extraction LLM call failed: {e}")

    # Fallback: keyword-based extraction
    return _fallback_extract_constraints(message, language, detected_tone)


def _fallback_extract_constraints(message: str, language: str, tone: str) -> ExtractedConstraints:
    """Keyword-based fallback when LLM fails."""
    msg_lower = message.lower()
    constraints = ExtractedConstraints(language_detected=language, tone_needed=tone)

    # Budget extraction
    budget_patterns = [
        r'(\d+)\s*(?:ke\s*)?(?:budget|under|below|below\s*?rs|rs\s*?(\d+)|₹\s*?(\d+))',
        r'(?:budget|under|below)\s*[:\s]*[₹rs]*\s*(\d+)',
        r'[₹rs]*\s*(\d+)\s*(?:ka\s*)?(?:budget|under|below)',
    ]
    for pattern in budget_patterns:
        match = re.search(pattern, msg_lower)
        if match:
            amount = match.group(1) or match.group(2) or match.group(3)
            if amount and amount.isdigit():
                constraints.budget_max = float(amount)
                break

    # Time sensitivity
    urgency_keywords = ["jaldi", "fast", "quick", "asap", "urgent", "time kam", "late", "hurry", "quickly"]
    if any(kw in msg_lower for kw in urgency_keywords):
        constraints.time_sensitivity = "high"

    # Category detection
    if any(kw in msg_lower for kw in ["khana", "food", "khao", "khana", "meal", "restaurant", "order"]):
        constraints.category = "food"
    elif any(kw in msg_lower for kw in ["book", "appointment", "schedule", "meeting", "slot"]):
        constraints.category = "appointment"
        constraints.intent = "booking_request"
    elif any(kw in msg_lower for kw in ["price", "cost", "kitna", "charges", "fees"]):
        constraints.intent = "pricing_query"

    # Dietary flags
    if "veg" in msg_lower:
        constraints.dietary_flags.append("veg")
    if "non-veg" in msg_lower or "non veg" in msg_lower:
        constraints.dietary_flags.append("non-veg")
    if "jain" in msg_lower:
        constraints.dietary_flags.append("jain")

    return constraints


# ---------------------------------------------------------------------------
# 3. Constraint-to-query translation + catalog filtering
# ---------------------------------------------------------------------------

def build_catalog_query(constraints: ExtractedConstraints) -> Dict[str, Any]:
    """
    Translate constraints into a structured filter query.
    This is what gets executed against catalog_items.
    """
    filters = {
        "available": True,
    }

    if constraints.budget_max is not None:
        filters["price__lte"] = constraints.budget_max

    if constraints.budget_min is not None:
        filters["price__gte"] = constraints.budget_min

    if constraints.prep_time_max_minutes is not None:
        filters["prep_time_minutes__lte"] = constraints.prep_time_max_minutes

    if constraints.category:
        filters["category__iexact"] = constraints.category

    if constraints.dietary_flags:
        filters["tags__contains"] = constraints.dietary_flags

    return filters


def apply_catalog_filters(items: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply constraint filters to catalog items."""
    filtered = []
    for item in items:
        match = True
        constraint_satisfied = {}

        if "price__lte" in filters and item.get("price", 0) > filters["price__lte"]:
            match = False
            constraint_satisfied["budget"] = False
        else:
            constraint_satisfied["budget"] = True

        if "price__gte" in filters and item.get("price", 0) < filters["price__gte"]:
            match = False
            constraint_satisfied["budget_min"] = False

        if "prep_time_minutes__lte" in filters and item.get("prep_time_minutes", 999) > filters["prep_time_minutes__lte"]:
            match = False
            constraint_satisfied["prep_time"] = False
        else:
            constraint_satisfied["prep_time"] = True

        if "category__iexact" in filters and item.get("category", "").lower() != filters["category__iexact"].lower():
            match = False
            constraint_satisfied["category"] = False

        if "tags__contains" in filters:
            required_tags = filters["tags__contains"]
            item_tags = [t.lower() for t in item.get("tags", [])]
            if not all(t.lower() in item_tags for t in required_tags):
                match = False
                constraint_satisfied["dietary"] = False

        if match:
            item["_constraint_satisfied"] = constraint_satisfied
            filtered.append(item)

    return filtered


# ---------------------------------------------------------------------------
# 4. Ranking
# ---------------------------------------------------------------------------

def rank_catalog_items(
    items: List[Dict[str, Any]],
    constraints: ExtractedConstraints,
) -> List[CatalogMatch]:
    """
    Rank items by relevance: priority (owner-set) + popularity + margin.
    Higher score = better match.
    """
    ranked = []
    for item in items:
        score = 0.0
        satisfied = item.get("_constraint_satisfied", {})

        # Owner-set priority (0-100)
        score += item.get("priority", 0) * 2

        # Popularity (0-100)
        score += item.get("popularity_score", 0) * 0.5

        # Margin tie-break (0-1 -> 0-50)
        score += item.get("margin", 0.0) * 50

        # Budget match bonus
        if constraints.budget_max and item.get("price", 0) <= constraints.budget_max:
            score += 20
            satisfied["budget"] = True

        # Time match bonus
        if constraints.prep_time_max_minutes and item.get("prep_time_minutes", 999) <= constraints.prep_time_max_minutes:
            score += 20
            satisfied["prep_time"] = True

        ranked.append(CatalogMatch(
            item_id=item.get("id", 0),
            name=item.get("name", ""),
            price=item.get("price", 0.0),
            prep_time_minutes=item.get("prep_time_minutes", 0),
            prep_time_tier=item.get("prep_time_tier", "normal"),
            category=item.get("category", ""),
            tags=item.get("tags", []),
            available=item.get("available", True),
            match_score=score,
            constraint_satisfied=satisfied,
        ))

    ranked.sort(key=lambda x: x.match_score, reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# 5. Fallback handling — relax least-critical constraint
# ---------------------------------------------------------------------------

def find_relaxable_constraint(
    matches: List[CatalogMatch],
    constraints: ExtractedConstraints,
    policy: Dict[str, Any],
) -> Tuple[List[CatalogMatch], Optional[str]]:
    """
    If no items match all constraints, relax the least-critical one.
    Returns (new_matches, relaxed_constraint_name).
    """
    if matches:
        return matches, None

    # Relaxation order depends on owner policy
    relaxation_policy = policy.get("relaxation_policy", "prefer_speed")

    if relaxation_policy == "prefer_speed":
        relax_order = ["prep_time", "budget"]
    elif relaxation_policy == "prefer_budget":
        relax_order = ["budget", "prep_time"]
    else:  # strict
        return [], None

    for constraint_name in relax_order:
        relaxed_matches = _relax_constraint(constraint_name, constraints)
        if relaxed_matches:
            return relaxed_matches, constraint_name

    return [], None


def _relax_constraint(constraint_name: str, constraints: ExtractedConstraints) -> List[Dict[str, Any]]:
    """Relax a single constraint and re-query catalog."""
    # This is a simplified version — in production, re-query with relaxed filter
    # For now, return empty to indicate no relaxed matches found
    return []


# ---------------------------------------------------------------------------
# 6. Response composition — human-like, tone-mirroring
# ---------------------------------------------------------------------------

RESPONSE_TEMPLATES = {
    "hi_en": {
        "single_match": "Bhai, {name} best rahega tere liye — ₹{price} mein, {prep_time} min mein ready hai. Chalega?",
        "multiple_match": "Bhai, tere budget ke under yeh options best hai:\n\n1. {name_1} — ₹{price_1} ({prep_time_1} min)\n2. {name_2} — ₹{price_2} ({prep_time_2} min)\n\nKonsa chahiye?",
        "relaxed": "Bhai, jaldi mein hai toh ye best rahega: {name} — ₹{price}, {prep_time} min. Thoda zyada time lega but fresh banega. Chalega?",
        "no_match": "Bhai, abhi kuch available nahi hai tere budget mein. Naya menu add kar rahe hain, ek minute ruk!",
    },
    "en": {
        "single_match": "I found a great match for you: {name} at ₹{price}, ready in {prep_time} mins. Want to go with this?",
        "multiple_match": "Here are the best options within your budget:\n\n1. {name_1} — ₹{price_1} ({prep_time_1} mins)\n2. {name_2} — ₹{price_2} ({prep_time_2} mins)\n\nWhich one would you like?",
        "relaxed": "The fastest available is {name} at ₹{price}, takes {prep_time} mins. It's slightly above your budget but worth it. Should I book it?",
        "no_match": "Nothing matches your constraints right now. We're adding new items — want me to notify you?",
    },
    "hi": {
        "single_match": "सर, {name} आपके लिए बेस्ट है — ₹{price} में, {prep_time} मिनट में तैयार है। चलेंगा?",
        "multiple_match": "सर, आपके बजट में ये ऑप्शन्स बेस्ट हैं:\n\n1. {name_1} — ₹{price_1} ({prep_time_1} मिनट)\n2. {name_2} — ₹{price_2} ({prep_time_2} मिनट)\n\nकौन सा चाहिए?",
        "relaxed": "सर, जल्दी में है तो ये बेस्ट रहेगा: {name} — ₹{price}, {prep_time} मिनट। थोड़ा ज्यादा समय लेगा लेकिन फ्रेश बनेगा। चलेंगा?",
        "no_match": "सर, अभी कुछ उपलब्ध नहीं है आपके बजट में। नया मेनू जोड़ रहे हैं, एक मिनट रुकें!",
    },
}


def compose_reply(
    matches: List[CatalogMatch],
    relaxed: Optional[str],
    constraints: ExtractedConstraints,
    owner_name: str = "सर",
) -> str:
    """
    Compose a human-like reply from catalog matches.
    Returns 1-2 concrete options, not a full catalog dump.
    """
    lang = constraints.language_detected if constraints.language_detected in RESPONSE_TEMPLATES else "hi_en"
    templates = RESPONSE_TEMPLATES.get(lang, RESPONSE_TEMPLATES["hi_en"])

    if not matches:
        return templates["no_match"]

    if relaxed:
        top = matches[0]
        return templates["relaxed"].format(
            name=top.name,
            price=int(top.price),
            prep_time=top.prep_time_minutes,
        )

    if len(matches) == 1:
        top = matches[0]
        return templates["single_match"].format(
            name=top.name,
            price=int(top.price),
            prep_time=top.prep_time_minutes,
        )

    top_two = matches[:2]
    return templates["multiple_match"].format(
        name_1=top_two[0].name,
        price_1=int(top_two[0].price),
        prep_time_1=top_two[0].prep_time_minutes,
        name_2=top_two[1].name,
        price_2=int(top_two[1].price),
        prep_time_2=top_two[1].prep_time_minutes,
    )


# ---------------------------------------------------------------------------
# 7. Main entry point — generate constraint-aware reply
# ---------------------------------------------------------------------------

async def generate_constraint_reply(
    owner_id: int,
    message: str,
    language: str = "auto",
) -> str:
    """
    Full pipeline: extract constraints → filter catalog → rank → compose reply.

    Args:
        owner_id: Owner/business ID
        message: User message
        language: Language hint or "auto"

    Returns:
        Human-like reply string
    """
    from services.onboarding import get_owner_catalog, get_owner_policy

    # Step 1: Extract constraints
    constraints = await extract_constraints(message, language)

    # Step 2: Get owner's catalog
    catalog = await get_owner_catalog(owner_id)
    if not catalog:
        return "Hi! I'm setting up my menu. Please check back in a few minutes. 🙏"

    # Step 3: Build filters and apply
    filters = build_catalog_query(constraints)
    filtered_items = apply_catalog_filters(catalog, filters)

    # Step 4: Rank
    matches = rank_catalog_items(filtered_items, constraints)

    # Step 5: Fallback — relax constraint if no matches
    policy = {}
    try:
        policy_obj = await get_owner_policy(owner_id)
        if policy_obj:
            policy = {
                "relaxation_policy": policy_obj.relaxation_policy,
                "max_autonomous_discount_pct": policy_obj.max_autonomous_discount_pct,
            }
    except Exception:
        pass

    matches, relaxed = find_relaxable_constraint(matches, constraints, policy)

    # Step 6: Compose reply
    reply = compose_reply(matches, relaxed, constraints)

    # Apply spell-check if available
    try:
        from utils.integrations import spellcheck_business_reply
        reply = await spellcheck_business_reply(reply, constraints.language_detected)
    except Exception:
        pass

    return reply


# ---------------------------------------------------------------------------
# 8. Complaint detection → escalation
# ---------------------------------------------------------------------------

COMPLAINT_PATTERNS = [
    r"itna\s*time\s*kyu\s*lagta\s*hai",
    r"why\s*does\s*it\s*take\s*so\s*long",
    r"worst|terrible|awful|horrible|bad\s*service",
    r"frustrated|annoyed|angry|upset",
    r"never\s*again|waste\s*of\s*time",
    r"complaint|grievance|problem\s*with",
]


def detect_complaint(message: str) -> bool:
    """Detect complaint-toned messages regardless of surface keywords."""
    msg_lower = message.lower()
    for pattern in COMPLAINT_PATTERNS:
        if re.search(pattern, msg_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# 9. Negotiation bounds checker
# ---------------------------------------------------------------------------

def check_negotiation_bounds(
    requested_discount_pct: float,
    owner_policy: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """
    Check if a discount request is within owner-configured bounds.
    Returns (allowed, reason_if_not).
    """
    max_discount = owner_policy.get("max_autonomous_discount_pct", 5.0)
    if requested_discount_pct <= max_discount:
        return True, None
    return False, f"Discount above allowed limit ({max_discount}%). Need human approval."
