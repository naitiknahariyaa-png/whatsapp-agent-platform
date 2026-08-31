"""
Constraint Extraction Eval Set — 20+ mixed Hinglish/English examples.

Each example has:
- message: the user's raw message
- expected_intent: what the constraint engine should extract
- expected_constraints: key constraints that must be present
- language: expected detected language
"""
from typing import Dict, Any, List


EVAL_SET: List[Dict[str, Any]] = [
    {
        "id": 1,
        "message": "hello mere ko kuch khana hai per mere pass 250 k buget hai kuch bata do aur mere pass time kam hai kuch jaldi kuch ho sakta hai kya",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 250,
            "time_sensitivity": "high",
            "category": "food",
        },
        "language": "hi_en",
    },
    {
        "id": 2,
        "message": "I want something under 500 rupees, preferably veg, and I need it within 20 minutes",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 500,
            "prep_time_max_minutes": 20,
            "dietary_flags": ["veg"],
        },
        "language": "en",
    },
    {
        "id": 3,
        "message": "bhaiya mujhe kuch chaiye jo 150 ke andar ho, aur jaldi se ban jaye",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 150,
            "time_sensitivity": "high",
        },
        "language": "hi_en",
    },
    {
        "id": 4,
        "message": "kitna hai ye? batao price",
        "expected_intent": "pricing_query",
        "expected_constraints": {},
        "language": "hi_en",
    },
    {
        "id": 5,
        "message": "I need to book an appointment for tomorrow evening",
        "expected_intent": "booking_request",
        "expected_constraints": {
            "category": "appointment",
        },
        "language": "en",
    },
    {
        "id": 6,
        "message": "mujhe ek meeting chahiye kal subah 10 baje",
        "expected_intent": "booking_request",
        "expected_constraints": {
            "category": "appointment",
        },
        "language": "hi_en",
    },
    {
        "id": 7,
        "message": "do you have anything in the 200-300 range? non-veg preferred",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_min": 200,
            "budget_max": 300,
            "dietary_flags": ["non-veg"],
        },
        "language": "en",
    },
    {
        "id": 8,
        "message": "time kam hai, kuch fast bata",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "time_sensitivity": "high",
        },
        "language": "hi_en",
    },
    {
        "id": 9,
        "message": "I want a jain thali under 400",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 400,
            "dietary_flags": ["jain"],
        },
        "language": "en",
    },
    {
        "id": 10,
        "message": "bhai 1000 ka budget hai, kuch accha suggest kar",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 1000,
        },
        "language": "hi_en",
    },
    {
        "id": 11,
        "message": "aur kitna time lega delivery?",
        "expected_intent": "support_question",
        "expected_constraints": {},
        "language": "hi_en",
    },
    {
        "id": 12,
        "message": "can I get a refund? the order was wrong",
        "expected_intent": "support_question",
        "expected_constraints": {},
        "language": "en",
    },
    {
        "id": 13,
        "message": "mujhe 2 plate chahiye chicken biryani",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "quantity": 2,
            "category": "food",
        },
        "language": "hi_en",
    },
    {
        "id": 14,
        "message": "what's the cheapest thing on the menu?",
        "expected_intent": "pricing_query",
        "expected_constraints": {},
        "language": "en",
    },
    {
        "id": 15,
        "message": "I'm in a hurry, what's ready right now?",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "time_sensitivity": "high",
        },
        "language": "en",
    },
    {
        "id": 16,
        "message": "250 ke andar kuch nhi hai kya?",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 250,
        },
        "language": "hi_en",
    },
    {
        "id": 17,
        "message": "I need something healthy and low calorie under 300",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 300,
            "dietary_flags": ["healthy"],
        },
        "language": "en",
    },
    {
        "id": 18,
        "message": "kuch spicy chahiye bhai, 200 ke andar",
        "expected_intent": "product_recommendation",
        "expected_constraints": {
            "budget_max": 200,
            "dietary_flags": ["spicy"],
        },
        "language": "hi_en",
    },
    {
        "id": 19,
        "message": "can I cancel my order?",
        "expected_intent": "support_question",
        "expected_constraints": {},
        "language": "en",
    },
    {
        "id": 20,
        "message": "aur batao kya options hai",
        "expected_intent": "product_recommendation",
        "expected_constraints": {},
        "language": "hi_en",
    },
    {
        "id": 21,
        "message": "mujhe appointment book karna hai par pehle price batao",
        "expected_intent": "pricing_query",
        "expected_constraints": {
            "category": "appointment",
        },
        "language": "hi_en",
    },
    {
        "id": 22,
        "message": "I want to speak to a human, this bot is useless",
        "expected_intent": "escalation",
        "expected_constraints": {},
        "language": "en",
    },
]


def get_eval_set() -> List[Dict[str, Any]]:
    """Return the full eval set for constraint extraction testing."""
    return EVAL_SET


def get_eval_summary() -> Dict[str, Any]:
    """Return summary statistics of the eval set."""
    intents = {}
    languages = {}
    has_budget = 0
    has_time = 0
    has_dietary = 0

    for example in EVAL_SET:
        intent = example["expected_intent"]
        intents[intent] = intents.get(intent, 0) + 1

        lang = example["language"]
        languages[lang] = languages.get(lang, 0) + 1

        constraints = example.get("expected_constraints", {})
        if "budget_max" in constraints or "budget_min" in constraints:
            has_budget += 1
        if "time_sensitivity" in constraints or "prep_time_max_minutes" in constraints:
            has_time += 1
        if "dietary_flags" in constraints:
            has_dietary += 1

    return {
        "total_examples": len(EVAL_SET),
        "intents": intents,
        "languages": languages,
        "with_budget_constraint": has_budget,
        "with_time_constraint": has_time,
        "with_dietary_constraint": has_dietary,
    }
