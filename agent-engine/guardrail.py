"""
Guardrail Layer
===============

Screens both inbound and outbound messages for:
- PII leakage (phone, email, PAN, Aadhaar, credit card, etc.)
- Off-brand tone (too formal, too casual, profanity)
- Policy violations (medical advice, legal advice, financial advice without disclaimer)
- Prompt injection attempts
- Off-topic responses

Runs on both inbound (before processing) and outbound (before sending).
"""
import re
import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("guardrail")


class GuardrailAction(Enum):
    """Action to take when a guardrail triggers."""
    ALLOW = "allow"           # Pass through
    REDACT = "redact"         # Remove/mask sensitive parts
    BLOCK = "block"           # Block entirely, return safe fallback
    FLAG = "flag"             # Allow but flag for review
    ESCALATE = "escalate"     # Escalate to human


class GuardrailCategory(Enum):
    PII = "pii"
    TONE = "tone"
    POLICY = "policy"
    INJECTION = "injection"
    OFF_TOPIC = "off_topic"
    MEDICAL_ADVICE = "medical_advice"
    LEGAL_ADVICE = "legal_advice"
    FINANCIAL_ADVICE = "financial_advice"


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""
    category: GuardrailCategory
    action: GuardrailAction
    matched_patterns: List[str] = field(default_factory=list)
    redacted_text: Optional[str] = None
    message: str = ""
    severity: int = 1  # 1=low, 2=medium, 3=high


@dataclass
class GuardrailConfig:
    """Configuration for a guardrail rule."""
    category: GuardrailCategory
    patterns: List[str]
    action: GuardrailAction = GuardrailAction.REDACT
    severity: int = 1
    description: str = ""


# ─── PII Patterns ──────────────────────────────────────────────────

PII_PATTERNS = {
    "phone": [
        r'\b(?:\+?91[\s-]?)?[6-9]\d{9}\b',  # Indian mobile
        r'\b\+?\d{1,3}[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{4}\b',  # International
    ],
    "email": [
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    ],
    "pan": [
        r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',  # PAN card
    ],
    "aadhaar": [
        r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',  # Aadhaar
    ],
    "credit_card": [
        r'\b(?:\d{4}[\s-]?){3}\d{4}\b',  # Credit card
    ],
    "bank_account": [
        r'\b\d{9,18}\b',  # Bank account (generic)
    ],
    "ifsc": [
        r'\b[A-Z]{4}0[A-Z0-9]{6}\b',  # IFSC code
    ],
    "gstin": [
        r'\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d][Z][A-Z\d]\b',  # GSTIN
    ],
}

# ─── Tone Patterns ─────────────────────────────────────────────────

TONE_PATTERNS = {
    "profanity": [
        r'\b(?:fuck|shit|bitch|asshole|bastard|damn|crap|hell)\b',
        r'\b(?:chutiya|madarchod|bhenchod|gaand|lund|chut)\b',  # Hindi profanity
    ],
    "overly_formal": [
        r'\b(?:hereby|herewith|aforementioned|pursuant to|in accordance with)\b',
    ],
    "overly_casual": [
        r'\b(?:yo|wassup|sup|hey there|what\'s up)\b',
    ],
    "aggressive": [
        r'\b(?:you must|you have to|i demand|unacceptable|ridiculous)\b',
    ],
}

# ─── Policy Violation Patterns ─────────────────────────────────────

POLICY_PATTERNS = {
    "medical_advice": [
        r'\b(?:take|take\s+|you\s+should\s+take|prescribe|medication|dosage|mg|tablet|capsule|injection)\b.*\b(?:fever|pain|cough|cold|infection|disease|condition|symptom)\b',
        r'\b(?:diagnose|diagnosis|treatment|therapy|cure|remedy)\b.*\b(?:medical|health|doctor)\b',
    ],
    "legal_advice": [
        r'\b(?:you\s+should\s+sue|file\s+a\s+case|legal\s+action|lawsuit|court|lawyer|advocate)\b.*\b(?:property|divorce|criminal|civil|contract)\b',
        r'\b(?:your\s+rights\s+are|the\s+law\s+says|legally\s+speaking|as\s+per\s+law)\b',
    ],
    "financial_advice": [
        r'\b(?:invest\s+in|buy\s+stock|mutual\s+fund|sip|returns|guaranteed\s+returns|risk-free)\b',
        r'\b(?:tax\s+evasion|avoid\s+tax|hide\s+income|black\s+money)\b',
    ],
}

# ─── Injection Patterns ────────────────────────────────────────────

INJECTION_PATTERNS = [
    r'ignore\s+(?:previous|above|all)\s+(?:instructions|prompts|rules)',
    r'forget\s+(?:everything|all\s+context|previous)',
    r'you\s+are\s+now\s+(?:a|an)\s+(?:hacker|admin|root|unrestricted)',
    r'override\s+(?:safety|security|guidelines|rules)',
    r'system\s+prompt',
    r'<\|.*?\|>',  # Token manipulation
    r'###\s*(?:instruction|system|user|assistant)',
]

# ─── Off-Topic Patterns ────────────────────────────────────────────

OFF_TOPIC_PATTERNS = [
    r'\b(?:weather|cricket|bollywood|movie|celebrity|gossip|politics|election)\b',
    r'\b(?:joke|riddle|poem|story|song|lyrics|recipe)\b',
    r'\b(?:homework|assignment|exam|test|quiz)\b',
]


class GuardrailEngine:
    """
    Fast, rule-based guardrail engine for screening messages.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._compile_patterns()
        self._stats = {"checked": 0, "flagged": 0, "redacted": 0, "blocked": 0}

    def _compile_patterns(self):
        """Compile all regex patterns for performance."""
        self._pii_regex = {}
        for category, patterns in PII_PATTERNS.items():
            self._pii_regex[category] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self._tone_regex = {}
        for category, patterns in TONE_PATTERNS.items():
            self._tone_regex[category] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self._policy_regex = {}
        for category, patterns in POLICY_PATTERNS.items():
            self._policy_regex[category] = [re.compile(p, re.IGNORECASE) for p in patterns]

        self._injection_regex = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
        self._off_topic_regex = [re.compile(p, re.IGNORECASE) for p in OFF_TOPIC_PATTERNS]

    def check_inbound(self, text: str, context: Optional[Dict] = None) -> List[GuardrailResult]:
        """Screen an inbound user message."""
        results = []
        results.extend(self._check_pii(text))
        results.extend(self._check_injection(text))
        results.extend(self._check_off_topic(text))
        self._stats["checked"] += 1
        return results

    def check_outbound(self, text: str, context: Optional[Dict] = None) -> List[GuardrailResult]:
        """Screen an outbound bot response before sending."""
        results = []
        results.extend(self._check_pii(text))
        results.extend(self._check_tone(text))
        results.extend(self._check_policy(text))
        results.extend(self._check_off_topic(text))
        self._stats["checked"] += 1
        return results

    def _check_pii(self, text: str) -> List[GuardrailResult]:
        results = []
        for category, regexes in self._pii_regex.items():
            for regex in regexes:
                matches = list(regex.finditer(text))
                if matches:
                    matched_texts = [m.group() for m in matches]
                    redacted = regex.sub(lambda m: self._redact_pii(m.group(), category), text)
                    results.append(GuardrailResult(
                        category=GuardrailCategory.PII,
                        action=GuardrailAction.REDACT,
                        matched_patterns=matched_texts,
                        redacted_text=redacted,
                        message=f"PII detected: {category}",
                        severity=3,
                    ))
        return results

    def _check_tone(self, text: str) -> List[GuardrailResult]:
        results = []
        for category, regexes in self._tone_regex.items():
            for regex in regexes:
                matches = list(regex.finditer(text))
                if matches:
                    matched_texts = [m.group() for m in matches]
                    results.append(GuardrailResult(
                        category=GuardrailCategory.TONE,
                        action=GuardrailAction.FLAG,
                        matched_patterns=matched_texts,
                        message=f"Tone issue: {category}",
                        severity=2,
                    ))
        return results

    def _check_policy(self, text: str) -> List[GuardrailResult]:
        results = []
        for category, regexes in self._policy_regex.items():
            for regex in regexes:
                matches = list(regex.finditer(text))
                if matches:
                    matched_texts = [m.group() for m in matches]
                    results.append(GuardrailResult(
                        category=GuardrailCategory(category.upper()),
                        action=GuardrailAction.BLOCK,
                        matched_patterns=matched_texts,
                        message=f"Policy violation: {category}",
                        severity=3,
                    ))
        return results

    def _check_injection(self, text: str) -> List[GuardrailResult]:
        results = []
        for regex in self._injection_regex:
            matches = list(regex.finditer(text))
            if matches:
                matched_texts = [m.group() for m in matches]
                results.append(GuardrailResult(
                    category=GuardrailCategory.INJECTION,
                    action=GuardrailAction.BLOCK,
                    matched_patterns=matched_texts,
                    message="Prompt injection attempt detected",
                    severity=3,
                ))
        return results

    def _check_off_topic(self, text: str) -> List[GuardrailResult]:
        results = []
        for regex in self._off_topic_regex:
            matches = list(regex.finditer(text))
            if matches:
                matched_texts = [m.group() for m in matches]
                results.append(GuardrailResult(
                    category=GuardrailCategory.OFF_TOPIC,
                    action=GuardrailAction.FLAG,
                    matched_patterns=matched_texts,
                    message="Potentially off-topic content",
                    severity=1,
                ))
        return results

    def _redact_pii(self, matched: str, category: str) -> str:
        """Redact PII based on category."""
        if category == "phone":
            return "+91-XXXXX-XXXXX"
        elif category == "email":
            return "xxx@xxx.xxx"
        elif category == "pan":
            return "XXXXX0000X"
        elif category == "aadhaar":
            return "XXXX-XXXX-XXXX"
        elif category == "credit_card":
            return "XXXX-XXXX-XXXX-XXXX"
        elif category == "ifsc":
            return "XXXX0XXXXXX"
        elif category == "gstin":
            return "XX" + "X" * 13
        return "[REDACTED]"

    def apply_redactions(self, text: str, results: List[GuardrailResult]) -> str:
        """Apply all REDACT actions to text."""
        for result in results:
            if result.action == GuardrailAction.REDACT and result.redacted_text:
                return result.redacted_text
        return text

    def get_decision(self, results: List[GuardrailResult]) -> GuardrailAction:
        """Determine overall action from multiple results."""
        if any(r.action == GuardrailAction.BLOCK for r in results):
            return GuardrailAction.BLOCK
        if any(r.action == GuardrailAction.REDACT for r in results):
            return GuardrailAction.REDACT
        if any(r.action == GuardrailAction.ESCALATE for r in results):
            return GuardrailAction.ESCALATE
        if any(r.action == GuardrailAction.FLAG for r in results):
            return GuardrailAction.FLAG
        return GuardrailAction.ALLOW

    def process_inbound(self, text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """Full inbound processing pipeline."""
        results = self.check_inbound(text, context)
        action = self.get_decision(results)

        processed_text = text
        if action == GuardrailAction.REDACT:
            processed_text = self.apply_redactions(text, results)

        return {
            "original": text,
            "processed": processed_text,
            "action": action.value,
            "results": [r.__dict__ for r in results],
            "allowed": action != GuardrailAction.BLOCK,
        }

    def process_outbound(self, text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """Full outbound processing pipeline."""
        results = self.check_outbound(text, context)
        action = self.get_decision(results)

        processed_text = text
        if action == GuardrailAction.REDACT:
            processed_text = self.apply_redactions(text, results)
        elif action == GuardrailAction.BLOCK:
            processed_text = self._get_safe_fallback(context)

        return {
            "original": text,
            "processed": processed_text,
            "action": action.value,
            "results": [r.__dict__ for r in results],
            "allowed": action != GuardrailAction.BLOCK,
        }

    def _get_safe_fallback(self, context: Optional[Dict] = None) -> str:
        """Safe fallback message when outbound is blocked."""
        vertical = context.get("vertical", "general") if context else "general"
        fallbacks = {
            "doctor": "I'm unable to provide that response. Please consult a doctor for medical advice. 🏥",
            "lawyer": "I'm unable to provide legal advice. Please consult a qualified lawyer. ⚖️",
            "ca": "I'm unable to provide financial advice. Please consult a CA. 📊",
            "general": "I'm unable to provide that response. How else can I help you?",
        }
        return fallbacks.get(vertical, fallbacks["general"])

    def get_stats(self) -> Dict[str, int]:
        return self._stats.copy()


# ─── Global Instance ──────────────────────────────────────────────

guardrail_engine = GuardrailEngine()


# ─── Integration Helpers ───────────────────────────────────────────

def check_inbound_message(text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    """Quick helper for inbound message checking."""
    return guardrail_engine.process_inbound(text, context)


def check_outbound_message(text: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    """Quick helper for outbound message checking."""
    return guardrail_engine.process_outbound(text, context)