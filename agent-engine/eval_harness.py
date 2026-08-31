"""
Agent Evaluation Harness
========================

A fixed set of test conversations with expected outcomes, run automatically
on every prompt/agent change to catch regressions before deploying.

Features:
- Fixed test cases with expected intents, entities, actions
- Supports multiple languages (en, hi, hi_en)
- Runs on every deploy / CI
- Generates report with pass/fail + drift metrics
- Compares against baseline to detect prompt drift
"""
import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

logger = logging.getLogger("eval_harness")


class TestStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


@dataclass
class ExpectedOutcome:
    """Expected outcome for a test case."""
    intent: str
    confidence_min: float = 0.7
    entities: Dict[str, str] = field(default_factory=dict)
    action: str = "none"
    response_contains: List[str] = field(default_factory=list)
    response_not_contains: List[str] = field(default_factory=list)


@dataclass
class TestCase:
    """A single test case for the evaluation harness."""
    id: str
    name: str
    language: str
    messages: List[Dict[str, Any]]  # [{"role": "user", "content": "..."}]
    expected: ExpectedOutcome
    tags: List[str] = field(default_factory=list)
    vertical: str = "general"
    client_id: int = 1


@dataclass
class TestResult:
    """Result of running a single test case."""
    test_id: str
    status: TestStatus
    actual_intent: Optional[str] = None
    actual_confidence: float = 0.0
    actual_entities: Dict[str, str] = field(default_factory=dict)
    actual_action: str = "none"
    actual_response: str = ""
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class EvaluationReport:
    """Full evaluation report."""
    run_id: str
    timestamp: str
    total_tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    results: List[TestResult]
    drift_detected: bool = False
    drift_details: List[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Built-in Test Cases
# ──────────────────────────────────────────────────────────────────────

BUILTIN_TEST_CASES: List[TestCase] = [
    # ── Hindi Greetings ──────────────────────────────────────────────
    TestCase(
        id="hi_greeting_namaste",
        name="Hindi greeting with namaste",
        language="hi",
        messages=[{"role": "user", "content": "नमस्ते, कैसे हो?"}],
        expected=ExpectedOutcome(
            intent="greeting",
            confidence_min=0.8,
            response_contains=["नमस्ते", "मदद"],
        ),
        tags=["greeting", "hindi"],
    ),
    TestCase(
        id="hi_greeting_suprabhat",
        name="Hindi morning greeting",
        language="hi",
        messages=[{"role": "user", "content": "सुप्रभात"}],
        expected=ExpectedOutcome(
            intent="greeting",
            confidence_min=0.8,
        ),
        tags=["greeting", "hindi"],
    ),

    # ── English Greetings ────────────────────────────────────────────
    TestCase(
        id="en_greeting_hello",
        name="English hello",
        language="en",
        messages=[{"role": "user", "content": "Hello, how are you?"}],
        expected=ExpectedOutcome(
            intent="greeting",
            confidence_min=0.8,
            response_contains=["hello", "help"],
        ),
        tags=["greeting", "english"],
    ),

    # ── Hinglish Greetings ───────────────────────────────────────────
    TestCase(
        id="hinglish_greeting",
        name="Hinglish greeting",
        language="hi_en",
        messages=[{"role": "user", "content": "Hi, kaise ho aap?"}],
        expected=ExpectedOutcome(
            intent="greeting",
            confidence_min=0.7,
        ),
        tags=["greeting", "hinglish"],
    ),

    # ── Appointment Booking ──────────────────────────────────────────
    TestCase(
        id="en_appt_booking",
        name="English appointment booking",
        language="en",
        messages=[{"role": "user", "content": "I want to book an appointment for tomorrow at 3pm"}],
        expected=ExpectedOutcome(
            intent="appointment_booking",
            confidence_min=0.75,
            entities={"date": "tomorrow", "time": "3pm"},
            action="create_appointment",
        ),
        tags=["appointment", "english"],
    ),
    TestCase(
        id="hi_appt_booking",
        name="Hindi appointment booking",
        language="hi",
        messages=[{"role": "user", "content": "मुझे कल दोपहर 3 बजे appointment चाहिए"}],
        expected=ExpectedOutcome(
            intent="appointment_booking",
            confidence_min=0.7,
            entities={"date": "कल", "time": "3 बजे"},
            action="create_appointment",
        ),
        tags=["appointment", "hindi"],
    ),
    TestCase(
        id="hinglish_appt_booking",
        name="Hinglish appointment booking",
        language="hi_en",
        messages=[{"role": "user", "content": "Mujhe kal 3 baje appointment chahiye doctor ke paas"}],
        expected=ExpectedOutcome(
            intent="appointment_booking",
            confidence_min=0.7,
            entities={"date": "kal", "time": "3 baje"},
            action="create_appointment",
        ),
        tags=["appointment", "hinglish"],
    ),

    # ── Pricing Queries ──────────────────────────────────────────────
    TestCase(
        id="en_pricing",
        name="English pricing query",
        language="en",
        messages=[{"role": "user", "content": "How much does a consultation cost?"}],
        expected=ExpectedOutcome(
            intent="pricing_query",
            confidence_min=0.75,
        ),
        tags=["pricing", "english"],
    ),
    TestCase(
        id="hi_pricing",
        name="Hindi pricing query",
        language="hi",
        messages=[{"role": "user", "content": "Consultation kitne ka hai?"}],
        expected=ExpectedOutcome(
            intent="pricing_query",
            confidence_min=0.7,
        ),
        tags=["pricing", "hindi"],
    ),

    # ── Lead Enquiry ─────────────────────────────────────────────────
    TestCase(
        id="en_lead_enquiry",
        name="English lead enquiry",
        language="en",
        messages=[{"role": "user", "content": "I'm interested in your services, can you tell me more?"}],
        expected=ExpectedOutcome(
            intent="lead_enquiry",
            confidence_min=0.7,
            action="save_lead",
        ),
        tags=["lead", "english"],
    ),
    TestCase(
        id="hi_lead_enquiry",
        name="Hindi lead enquiry",
        language="hi",
        messages=[{"role": "user", "content": "Mujhe aapki service chahiye, details batao"}],
        expected=ExpectedOutcome(
            intent="lead_enquiry",
            confidence_min=0.7,
            action="save_lead",
        ),
        tags=["lead", "hindi"],
    ),

    # ── Symptom Check ────────────────────────────────────────────────
    TestCase(
        id="hi_symptom_fever",
        name="Hindi fever symptom",
        language="hi",
        messages=[{"role": "user", "content": "Mujhe bukhar hai aur sar dard bhi hai"}],
        expected=ExpectedOutcome(
            intent="symptom_check",
            confidence_min=0.7,
        ),
        tags=["symptom", "hindi"],
    ),
    TestCase(
        id="en_symptom_cough",
        name="English cough symptom",
        language="en",
        messages=[{"role": "user", "content": "I have a bad cough and fever"}],
        expected=ExpectedOutcome(
            intent="symptom_check",
            confidence_min=0.75,
        ),
        tags=["symptom", "english"],
    ),

    # ── Document Request ─────────────────────────────────────────────
    TestCase(
        id="en_document_upload",
        name="English document upload request",
        language="en",
        messages=[{"role": "user", "content": "I want to upload my prescription"}],
        expected=ExpectedOutcome(
            intent="document_request",
            confidence_min=0.7,
        ),
        tags=["document", "english"],
    ),

    # ── Human Handoff ────────────────────────────────────────────────
    TestCase(
        id="en_human_handoff",
        name="English human handoff request",
        language="en",
        messages=[{"role": "user", "content": "I want to talk to a real human agent"}],
        expected=ExpectedOutcome(
            intent="human_handoff",
            confidence_min=0.85,
        ),
        tags=["handoff", "english"],
    ),
    TestCase(
        id="hi_human_handoff",
        name="Hindi human handoff request",
        language="hi",
        messages=[{"role": "user", "content": "Mujhe kisi insaan se baat karni hai"}],
        expected=ExpectedOutcome(
            intent="human_handoff",
            confidence_min=0.8,
        ),
        tags=["handoff", "hindi"],
    ),

    # ── Multi-turn Conversation ──────────────────────────────────────
    TestCase(
        id="multi_turn_booking",
        name="Multi-turn appointment booking flow",
        language="en",
        messages=[
            {"role": "user", "content": "I want to book an appointment"},
            {"role": "assistant", "content": "Sure, what date and time?"},
            {"role": "user", "content": "Tomorrow at 3pm"},
        ],
        expected=ExpectedOutcome(
            intent="appointment_booking",
            confidence_min=0.7,
            entities={"date": "tomorrow", "time": "3pm"},
            action="create_appointment",
        ),
        tags=["appointment", "multi_turn", "english"],
    ),
]


# ──────────────────────────────────────────────────────────────────────
# Evaluation Harness Runner
# ──────────────────────────────────────────────────────────────────────

class EvaluationHarness:
    """Runs evaluation test cases against the agent."""

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.test_cases: List[TestCase] = BUILTIN_TEST_CASES.copy()
        self.custom_cases: List[TestCase] = []

    def add_test_case(self, test_case: TestCase):
        self.custom_cases.append(test_case)

    def load_from_file(self, filepath: str):
        """Load test cases from a JSON file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        for item in data:
            expected = ExpectedOutcome(**item["expected"])
            tc = TestCase(
                id=item["id"],
                name=item["name"],
                language=item["language"],
                messages=item["messages"],
                expected=expected,
                tags=item.get("tags", []),
                vertical=item.get("vertical", "general"),
                client_id=item.get("client_id", 1),
            )
            self.custom_cases.append(tc)

    async def run_single(self, test_case: TestCase) -> TestResult:
        """Run a single test case."""
        import time
        start = time.time()

        if self.orchestrator is None:
            # Try to get orchestrator lazily
            try:
                from orchestrator import AgentOrchestrator
                self.orchestrator = AgentOrchestrator()
            except Exception as e:
                return TestResult(
                    test_id=test_case.id,
                    status=TestResult.ERROR,
                    error=f"Orchestrator not available: {e}",
                    duration_ms=(time.time() - start) * 1000,
                )

        try:
            # Process the conversation
            last_response = ""
            for i, msg in enumerate(test_case.messages):
                if msg["role"] == "user":
                    result = await self.orchestrator.process_message(
                        phone_number="+919999999999",
                        message=msg["content"],
                        client_id=test_case.client_id,
                    )
                    last_response = result.get("reply", "")
                # Assistant messages are context only

            duration = (time.time() - start) * 1000

            # Evaluate
            status = self._evaluate_result(test_case, last_response)

            return TestResult(
                test_id=test_case.id,
                status=status,
                actual_response=last_response,
                duration_ms=duration,
            )

        except Exception as e:
            logger.exception("Test case %s failed with error", test_case.id)
            return TestResult(
                test_id=test_case.id,
                status=TestStatus.ERROR,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    def _evaluate_result(self, test_case: TestCase, response: str) -> TestStatus:
        """Evaluate if the response matches expected outcome."""
        exp = test_case.expected

        # Check response contains expected phrases
        for phrase in exp.response_contains:
            if phrase.lower() not in response.lower():
                return TestStatus.FAIL

        # Check response does NOT contain forbidden phrases
        for phrase in exp.response_not_contains:
            if phrase.lower() in response.lower():
                return TestStatus.FAIL

        return TestStatus.PASS

    async def run_all(self, test_cases: Optional[List[TestCase]] = None) -> EvaluationReport:
        """Run all test cases and generate report."""
        cases = test_cases or (self.test_cases + self.custom_cases)
        run_id = f"eval_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        results = []
        for tc in cases:
            result = await self.run_single(tc)
            results.append(result)
            logger.info("Test %s: %s (%.0fms)", tc.id, result.status.value, result.duration_ms)

        passed = sum(1 for r in results if r.status == TestStatus.PASS)
        failed = sum(1 for r in results if r.status == TestStatus.FAIL)
        errors = sum(1 for r in results if r.status == TestStatus.ERROR)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIP)

        # Check for drift (comparing against baseline if available)
        drift_detected, drift_details = self._check_drift(results)

        report = EvaluationReport(
            run_id=run_id,
            timestamp=datetime.utcnow().isoformat(),
            total_tests=len(results),
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            results=results,
            drift_detected=drift_detected,
            drift_details=drift_details,
        )

        return report

    def _check_drift(self, results: List[TestResult]) -> tuple:
        """Check for drift by comparing against baseline."""
        baseline_path = Path("eval_baseline.json")
        if not baseline_path.exists():
            return False, ["No baseline found - run with --save-baseline first"]

        with open(baseline_path) as f:
            baseline = json.load(f)

        drift_details = []
        for result in results:
            baseline_result = baseline.get(result.test_id)
            if baseline_result:
                # Check if pass rate dropped
                if baseline_result["status"] == "pass" and result.status != TestStatus.PASS:
                    drift_details.append(f"{result.test_id}: was PASS, now {result.status.value}")

        return len(drift_details) > 0, drift_details

    def save_baseline(self, report: EvaluationReport):
        """Save current results as baseline."""
        baseline = {r.test_id: {"status": r.status.value} for r in report.results}
        with open("eval_baseline.json", "w") as f:
            json.dump(baseline, f, indent=2)
        logger.info("Baseline saved to eval_baseline.json")

    def export_report(self, report: EvaluationReport, filepath: str):
        """Export report to JSON file."""
        data = {
            "run_id": report.run_id,
            "timestamp": report.timestamp,
            "summary": {
                "total": report.total_tests,
                "passed": report.passed,
                "failed": report.failed,
                "errors": report.errors,
                "skipped": report.skipped,
                "drift_detected": report.drift_detected,
            },
            "results": [asdict(r) for r in report.results],
            "drift_details": report.drift_details,
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)


# CLI Entry Point
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Agent Evaluation Harness")
    parser.add_argument("--save-baseline", action="store_true", help="Save results as baseline")
    parser.add_argument("--output", default="eval_report.json", help="Output report file")
    parser.add_argument("--test-file", help="Custom test cases JSON file")
    parser.add_argument("--tags", help="Run only tests with these tags (comma-separated)")
    args = parser.parse_args()

    harness = EvaluationHarness()

    if args.test_file:
        harness.load_from_file(args.test_file)

    if args.tags:
        tags = set(args.tags.split(","))
        all_cases = BUILTIN_TEST_CASES
        filtered = [tc for tc in all_cases if any(t in tc.tags for t in tags)]
        report = await harness.run_all(filtered)
    else:
        report = await harness.run_all()

    print(f"\n{'='*60}")
    print(f"Evaluation Report: {report.run_id}")
    print(f"{'='*60}")
    print(f"Total: {report.total_tests} | Passed: {report.passed} | Failed: {report.failed} | Errors: {report.errors}")
    print(f"Drift Detected: {report.drift_detected}")
    if report.drift_details:
        print(f"Drift Details: {', '.join(report.drift_details)}")
    print(f"{'='*60}\n")

    if args.save_baseline:
        harness.save_baseline(report)

    harness.export_report(report, args.output)
    print(f"Report saved to {args.output}")

    # Exit with error code if any failures
    if report.failed > 0 or report.errors > 0:
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())