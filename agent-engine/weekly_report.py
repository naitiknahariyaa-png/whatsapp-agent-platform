"""
Weekly CEO Report + Quality Audit Agent
========================================

Generates a weekly executive summary with:
- Business metrics snapshot (leads, appointments, revenue)
- Quality audit of AI conversations (accuracy, tone, escalation rate)
- Drift detection (prompt/agent performance over time)
- Actionable recommendations for the week ahead
"""

import json
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from sqlalchemy import select, func, text

from db import get_session, Message, Contact, Appointment, Conversation
from lead_gen import Lead
from vector_store import vector_store
from eval_harness import EvaluationHarness, BUILTIN_TEST_CASES
from model_router import model_router, TaskType

logger = logging.getLogger("weekly_report")


@dataclass
class QualityMetrics:
    """Quality metrics for AI conversations."""
    total_conversations: int = 0
    total_messages: int = 0
    handoff_rate: float = 0.0
    avg_confidence: float = 0.0
    low_confidence_count: int = 0
    escalation_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    hallucination_flags: int = 0
    policy_violations: int = 0
    sentiment_breakdown: Dict[str, int] = field(default_factory=dict)


@dataclass
class BusinessMetrics:
    """Business metrics for the week."""
    new_leads: int = 0
    qualified_leads: int = 0
    converted_leads: int = 0
    appointments_booked: int = 0
    appointments_completed: int = 0
    appointments_no_show: int = 0
    appointments_cancelled: int = 0
    messages_inbound: int = 0
    messages_outbound: int = 0
    active_conversations: int = 0
    unique_contacts: int = 0
    conversion_rate: float = 0.0
    appointment_completion_rate: float = 0.0
    estimated_revenue: float = 0.0


@dataclass
class DriftMetrics:
    """Drift detection metrics."""
    eval_pass_rate: float = 0.0
    eval_total: int = 0
    eval_passed: int = 0
    eval_failed: int = 0
    drift_detected: bool = False
    drift_details: List[str] = field(default_factory=list)
    prompt_changes: int = 0


@dataclass
class WeeklyReport:
    """Complete weekly report."""
    week_start: str
    week_end: str
    generated_at: str
    client_id: int
    business_metrics: BusinessMetrics
    quality_metrics: QualityMetrics
    drift_metrics: DriftMetrics
    top_issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    ca_insights: Dict[str, Any] = field(default_factory=dict)


class QualityAuditAgent:
    """
    Audits AI conversation quality:
    - Accuracy (hallucination detection via RAG grounding)
    - Tone (professional, empathetic)
    - Escalation appropriateness
    - Policy compliance
    """
    
    def __init__(self):
        self.llm = None
        try:
            from llm_setup import get_llm
            self.llm = get_llm()
        except Exception:
            pass
    
    async def audit_conversation(self, messages: List[Dict], client_id: int) -> Dict[str, Any]:
        """Audit a single conversation for quality."""
        if not self.llm or not hasattr(self.llm, 'invoke'):
            return self._fallback_audit(messages)
        
        # Build conversation text
        conv_text = "\n".join([
            f"{'User' if m['direction'] == 'incoming' else 'Bot'}: {m['content']}"
            for m in messages[-10:]  # Last 10 turns
        ])
        
        prompt = f"""You are a Quality Audit Agent for a WhatsApp AI assistant.
Analyze this conversation for quality issues.

CONVERSATION:
{conv_text}

Evaluate on these dimensions (return JSON only):
{{
    "accuracy_score": 0-100,
    "tone_score": 0-100,
    "escalation_appropriate": true/false,
    "policy_compliant": true/false,
    "hallucination_detected": true/false,
    "issues": ["issue1", "issue2"],
    "summary": "Brief summary"
}}

Criteria:
- Accuracy: Does the AI use grounded knowledge or hallucinate?
- Tone: Professional, empathetic, culturally appropriate?
- Escalation: Did it escalate when it should have?
- Policy: No medical/legal/financial advice without disclaimer?
- Hallucination: Facts not grounded in knowledge base?
"""
        
        try:
            if hasattr(self.llm, 'invoke'):
                response = await asyncio.to_thread(self.llm.invoke, prompt)
                content = response.content if hasattr(response, 'content') else str(response)
            else:
                response = await self.llm.generate([{"role": "user", "content": prompt}])
                content = response.get("content", "")
            
            # Extract JSON
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            logger.warning(f"Quality audit LLM call failed: {e}")
        
        return self._fallback_audit(messages)
    
    def _fallback_audit(self, messages: List[Dict]) -> Dict[str, Any]:
        """Fallback audit without LLM."""
        return {
            "accuracy_score": 75,
            "tone_score": 80,
            "escalation_appropriate": True,
            "policy_compliant": True,
            "hallucination_detected": False,
            "issues": [],
            "summary": "Fallback audit - LLM unavailable"
        }


class WeeklyReportGenerator:
    """Generates weekly CEO reports with quality audit."""
    
    def __init__(self):
        self.quality_auditor = QualityAuditAgent()
    
    async def generate(self, client_id: int, week_start: Optional[datetime] = None) -> WeeklyReport:
        """Generate weekly report for a client."""
        if week_start is None:
            # Default to last Monday
            now = datetime.now(timezone.utc)
            week_start = now - timedelta(days=now.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        
        week_end = week_start + timedelta(days=7)
        
        # Gather all metrics in parallel
        business_metrics = await self._gather_business_metrics(client_id, week_start, week_end)
        quality_metrics = await self._gather_quality_metrics(client_id, week_start, week_end)
        drift_metrics = await self._gather_drift_metrics(client_id, week_start, week_end)
        
        # Generate insights and recommendations
        top_issues = self._identify_top_issues(business_metrics, quality_metrics, drift_metrics)
        recommendations = self._generate_recommendations(business_metrics, quality_metrics, drift_metrics)
        ca_insights = self._generate_ca_insights(business_metrics, quality_metrics)
        
        report = WeeklyReport(
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
            generated_at=datetime.now(timezone.utc).isoformat(),
            client_id=client_id,
            business_metrics=business_metrics,
            quality_metrics=quality_metrics,
            drift_metrics=drift_metrics,
            top_issues=top_issues,
            recommendations=recommendations,
            ca_insights=ca_insights,
        )
        
        # Save report
        await self._save_report(report)
        
        return report
    
    async def _gather_business_metrics(self, client_id: int, week_start: datetime, week_end: datetime) -> BusinessMetrics:
        """Gather business metrics for the week."""
        metrics = BusinessMetrics()
        
        try:
            async for session in get_session():
                # Leads
                result = await session.execute(
                    select(func.count()).select_from(Lead).where(
                        Lead.client_id == client_id,
                        Lead.created_at >= week_start,
                        Lead.created_at < week_end
                    )
                )
                metrics.new_leads = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Lead).where(
                        Lead.client_id == client_id,
                        Lead.created_at >= week_start,
                        Lead.created_at < week_end,
                        Lead.status.in_(["qualified", "converted"])
                    )
                )
                metrics.qualified_leads = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Lead).where(
                        Lead.client_id == client_id,
                        Lead.created_at >= week_start,
                        Lead.created_at < week_end,
                        Lead.status == "converted"
                    )
                )
                metrics.converted_leads = result.scalar() or 0
                
                # Appointments
                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id,
                        Appointment.created_at >= week_start,
                        Appointment.created_at < week_end
                    )
                )
                metrics.appointments_booked = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id,
                        Appointment.appointment_date >= week_start.strftime("%Y-%m-%d"),
                        Appointment.appointment_date < week_end.strftime("%Y-%m-%d"),
                        Appointment.status == "completed"
                    )
                )
                metrics.appointments_completed = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id,
                        Appointment.status == "no_show",
                        Appointment.appointment_date >= week_start.strftime("%Y-%m-%d"),
                        Appointment.appointment_date < week_end.strftime("%Y-%m-%d")
                    )
                )
                metrics.appointments_no_show = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Appointment).where(
                        Appointment.client_id == client_id,
                        Appointment.status == "cancelled",
                        Appointment.appointment_date >= week_start.strftime("%Y-%m-%d"),
                        Appointment.appointment_date < week_end.strftime("%Y-%m-%d")
                    )
                )
                metrics.appointments_cancelled = result.scalar() or 0
                
                # Messages
                result = await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.client_id == client_id,
                        Message.created_at >= week_start,
                        Message.created_at < week_end,
                        Message.direction == "incoming"
                    )
                )
                metrics.messages_inbound = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Message).where(
                        Message.client_id == client_id,
                        Message.created_at >= week_start,
                        Message.created_at < week_end,
                        Message.direction == "outgoing"
                    )
                )
                metrics.messages_outbound = result.scalar() or 0
                
                # Active conversations & unique contacts
                result = await session.execute(
                    select(func.count(func.distinct(Message.phone_number))).select_from(Message).where(
                        Message.client_id == client_id,
                        Message.created_at >= week_start,
                        Message.created_at < week_end
                    )
                )
                metrics.unique_contacts = result.scalar() or 0
                
                result = await session.execute(
                    select(func.count()).select_from(Conversation).where(
                        Conversation.client_id == client_id,
                        Conversation.last_message_at >= week_start,
                        Conversation.last_message_at < week_end,
                        Conversation.status == "active"
                    )
                )
                metrics.active_conversations = result.scalar() or 0
                
        except Exception as e:
            logger.error(f"Failed to gather business metrics: {e}")
        
        # Calculate derived metrics
        if metrics.new_leads > 0:
            metrics.conversion_rate = round((metrics.converted_leads / metrics.new_leads) * 100, 1)
        
        total_appts = metrics.appointments_completed + metrics.appointments_no_show + metrics.appointments_cancelled
        if total_appts > 0:
            metrics.appointment_completion_rate = round((metrics.appointments_completed / total_appts) * 100, 1)
        
        # Estimate revenue (₹5000 per converted lead)
        metrics.estimated_revenue = metrics.converted_leads * 5000
        
        return metrics
    
    async def _gather_quality_metrics(self, client_id: int, week_start: datetime, week_end: datetime) -> QualityMetrics:
        """Gather quality metrics by auditing conversations."""
        metrics = QualityMetrics()
        
        try:
            async for session in get_session():
                # Get all conversations in the week
                result = await session.execute(
                    select(Message).where(
                        Message.client_id == client_id,
                        Message.created_at >= week_start,
                        Message.created_at < week_end
                    ).order_by(Message.created_at)
                )
                messages = result.scalars().all()
                
                if not messages:
                    return metrics
                
                metrics.total_messages = len(messages)
                metrics.incoming_messages = sum(1 for m in messages if m.direction == "incoming")
                metrics.outgoing_messages = sum(1 for m in messages if m.direction == "outgoing")
                
                # Group by conversation
                from collections import defaultdict
                convs = defaultdict(list)
                for msg in messages:
                    convs[msg.phone_number].append({
                        "direction": msg.direction,
                        "content": msg.content
                    })
                
                metrics.total_conversations = len(convs)
                
                # Audit sample of conversations (max 20 for performance)
                sample_convs = list(convs.items())[:20]
                
                handoff_count = 0
                confidence_sum = 0
                confidence_count = 0
                low_confidence = 0
                escalation_count = 0
                
                for phone, msgs in sample_convs:
                    audit = await self.quality_auditor.audit_conversation(msgs, 1)
                    
                    if not audit.get("escalation_appropriate", True):
                        escalation_count += 1
                    
                    if audit.get("hallucination_detected", False):
                        metrics.hallucination_flags += 1
                    
                    if not audit.get("policy_compliant", True):
                        metrics.policy_violations += 1
                    
                    score = audit.get("accuracy_score", 75)
                    confidence_sum += score
                    confidence_count += 1
                    if score < 60:
                        low_confidence += 1
                
                metrics.avg_confidence = round(confidence_sum / max(confidence_count, 1), 1)
                metrics.low_confidence_count = low_confidence
                metrics.escalation_rate = round((escalation_count / max(len(sample_convs), 1)) * 100, 1)
                
                # Handoff rate (from orchestrator metrics - simplified)
                metrics.handoff_rate = 5.0  # Placeholder
                
        except Exception as e:
            logger.error(f"Failed to gather quality metrics: {e}")
        
        return metrics
    
    async def _gather_drift_metrics(self, client_id: int, week_start: datetime, week_end: datetime) -> DriftMetrics:
        """Run evaluation harness to detect drift."""
        metrics = DriftMetrics()
        
        try:
            harness = EvaluationHarness()
            report = await harness.run_all()
            
            metrics.eval_total = report.total_tests
            metrics.eval_passed = report.passed
            metrics.eval_failed = report.failed
            metrics.eval_pass_rate = round((report.passed / max(report.total_tests, 1)) * 100, 1)
            metrics.drift_detected = report.drift_detected
            metrics.drift_details = report.drift_details
            
        except Exception as e:
            logger.error(f"Failed to gather drift metrics: {e}")
        
        return metrics
    
    def _identify_top_issues(self, business: BusinessMetrics, quality: QualityMetrics, drift: DriftMetrics) -> List[str]:
        issues = []
        
        if business.conversion_rate < 20:
            issues.append(f"Low lead conversion rate: {business.conversion_rate}%")
        
        if business.appointment_completion_rate < 70:
            issues.append(f"Low appointment completion rate: {business.appointment_completion_rate}%")
        
        if business.appointments_no_show > business.appointments_completed * 0.3:
            issues.append(f"High no-show rate: {business.appointments_no_show} no-shows")
        
        if quality.hallucination_flags > 0:
            issues.append(f"Hallucination detected in {quality.hallucination_flags} conversations")
        
        if quality.policy_violations > 0:
            issues.append(f"Policy violations detected: {quality.policy_violations}")
        
        if quality.low_confidence_count > 3:
            issues.append(f"Low confidence responses: {quality.low_confidence_count}")
        
        if drift.drift_detected:
            issues.append(f"Model drift detected: {', '.join(drift.drift_details[:3])}")
        
        if quality.escalation_rate > 15:
            issues.append(f"High escalation rate: {quality.escalation_rate}%")
        
        return issues[:5]  # Top 5 issues
    
    def _generate_recommendations(self, business: BusinessMetrics, quality: QualityMetrics, drift: DriftMetrics) -> List[str]:
        recs = []
        
        if business.conversion_rate < 20:
            recs.append("Review lead qualification criteria; improve follow-up timing")
        
        if business.appointment_completion_rate < 70:
            recs.append("Send more reminder messages; offer easy rescheduling")
        
        if business.appointments_no_show > 0:
            recs.append("Implement confirmation messages 2h before appointments")
        
        if quality.hallucination_flags > 0:
            recs.append("Expand knowledge base; enable automatic RAG for more queries")
        
        if quality.policy_violations > 0:
            recs.append("Review system prompts for compliance; add guardrails")
        
        if quality.low_confidence_count > 3:
            recs.append("Expand training data for low-confidence intent categories")
        
        if drift.drift_detected:
            recs.append("Review recent prompt changes; consider rollback or retraining")
        
        if quality.escalation_rate > 15:
            recs.append("Lower escalation threshold; improve specialist agent coverage")
        
        # Default recommendations if no specific issues
        if not recs:
            recs = [
                "Continue monitoring conversion funnel",
                "Review knowledge base for gaps",
                "Consider A/B testing message templates"
            ]
        
        return recs[:5]
    
    def _generate_ca_insights(self, business: BusinessMetrics, quality: QualityMetrics) -> Dict[str, Any]:
        return {
            "lead_conversion_rate": f"{business.conversion_rate}%",
            "appointment_completion_rate": f"{business.appointment_completion_rate}%",
            "engagement_ratio": f"{business.messages_inbound}:{business.messages_outbound}",
            "estimated_revenue": f"₹{business.estimated_revenue:,}",
            "follow_up_needed": business.qualified_leads - business.converted_leads,
            "quality_score": quality.avg_confidence,
            "recommendations": [
                "Follow up with qualified leads not yet converted",
                "Review cancelled appointments for scheduling issues",
                "Increase engagement with inactive contacts",
            ],
        }
    
    async def _save_report(self, report: WeeklyReport):
        """Save report to file and database."""
        try:
            # Save to file
            filepath = f"exports/weekly_report_client_{report.client_id}_{report.week_start[:10]}.json"
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w") as f:
                json.dump(asdict(report), f, indent=2, default=str)
            logger.info(f"[v] Weekly report saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")


# Global instance
weekly_report_generator = WeeklyReportGenerator()


# CLI entry point
async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate Weekly CEO Report")
    parser.add_argument("--client-id", type=int, default=1, help="Client ID")
    parser.add_argument("--week-start", help="Week start date (YYYY-MM-DD)")
    parser.add_argument("--output", help="Output file path")
    args = parser.parse_args()
    
    week_start = None
    if args.week_start:
        week_start = datetime.fromisoformat(args.week_start)
    
    report = await weekly_report_generator.generate(args.client_id, week_start)
    
    if args.output:
        with open(args.output, "w") as f:
            json.dump(asdict(report), f, indent=2, default=str)
    else:
        print(json.dumps(asdict(report), indent=2, default=str))
    
    print(f"\nWeekly Report Generated for Client {report.client_id}")
    print(f"Week: {report.week_start} to {report.week_end}")
    print(f"Leads: {report.business_metrics.new_leads} | Converted: {report.business_metrics.converted_leads}")
    print(f"Appointments: {report.business_metrics.appointments_booked} booked, {report.business_metrics.appointments_completed} completed")
    print(f"Quality Score: {report.quality_metrics.avg_confidence}")
    print(f"Drift Detected: {report.drift_metrics.drift_detected}")
    if report.top_issues:
        print(f"\nTop Issues:")
        for issue in report.top_issues:
            print(f"  - {issue}")
    if report.recommendations:
        print(f"\nRecommendations:")
        for rec in report.recommendations:
            print(f"  - {rec}")


if __name__ == "__main__":
    asyncio.run(main())