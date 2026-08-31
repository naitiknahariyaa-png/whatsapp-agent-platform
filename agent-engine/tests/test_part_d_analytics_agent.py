"""
Part D tests — Analytics Agent (worker roster completion).

Verifies:
  * the specialist is registered on the Manager roster,
  * the Planner keyword-fallback routes reporting questions to it,
  * collect_metrics returns REAL numbers from the database,
  * the rule-based summary never invents figures and always ends with advice.
"""
import os
import sys

_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import pytest

from agents.analytics import AnalyticsAgent
from agents.manager import IntentType, Planner


# ---------------------------------------------------------------------------
# Registration & routing
# ---------------------------------------------------------------------------
def test_planner_routes_reporting_questions_to_analytics():
    plan = Planner()._keyword_fallback("send me this week's stats please")
    assert plan.intent == IntentType.ANALYTICS_REPORT.value
    assert plan.plan[0].agent == "analytics"
    assert plan.confidence >= 0.7


def test_planner_analytics_does_not_hijack_escalation_or_sales():
    planner = Planner()
    # Complaint tone still wins -> escalation
    assert planner._keyword_fallback(
        "this is terrible, I want a human").intent == IntentType.ESCALATION.value
    # Pricing question still wins -> sales
    assert planner._keyword_fallback(
        "what is the price of the pro plan").intent == IntentType.SALES_INQUIRY.value


@pytest.mark.asyncio
async def test_analytics_specialist_registered_on_manager_roster():
    from agents.manager import ManagerAgent
    mgr = ManagerAgent()
    names = mgr.registry.names
    assert "analytics" in names
    agent = mgr.registry.get("analytics")
    assert isinstance(agent, AnalyticsAgent)


# ---------------------------------------------------------------------------
# Real metrics + deterministic summary
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_collect_metrics_returns_real_numbers():
    from db import init_db, async_session, Contact, Message
    from crypto_fields import hmac_phone_hash
    from sqlalchemy import select

    await init_db()
    cid = 4242
    async with async_session() as session:
        contact = Contact(client_id=cid, phone_number="+919000000001",
                          phone_hash=hmac_phone_hash("+919000000001"), name="A")
        session.add(contact)
        session.add(Message(client_id=cid, phone_number="+919000000001",
                            phone_hash=hmac_phone_hash("+919000000001"),
                            content="hi", direction="incoming"))
        await session.commit()

    agent = AnalyticsAgent()
    m = await agent.collect_metrics(cid)

    assert m["available"] is True
    assert m["total_contacts"] >= 1
    assert m["total_messages"] >= 1
    assert "total_appointments" in m and "conversion_rate" in m


@pytest.mark.asyncio
async def test_run_reports_real_numbers_and_advice():
    from db import init_db
    await init_db()

    agent = AnalyticsAgent()
    reply = await agent.run("how did we do?", {"client_id": 777})

    # Never a raw error / empty string to the owner
    assert isinstance(reply, str) and len(reply) > 20
    assert "📊" in reply or "snapshot" in reply.lower()
    assert "💡 Advice:" in reply          # always closes with guidance
    assert "Traceback" not in reply and "Error" not in reply


def test_worst_funnel_stage_supports_objects_and_dicts():
    class Stage:
        def __init__(self, name, dropoff):
            self.name, self.dropoff = name, dropoff

    agent = AnalyticsAgent()
    objs = [Stage("visited", 3), Stage("replied", 9), Stage("booked", 1)]
    assert agent._worst_funnel_stage(objs) == ("replied", 9)
    dicts = [{"name": "a", "dropoff": 2}, {"name": "b", "dropoff": 5}]
    assert agent._worst_funnel_stage(dicts) == ("b", 5)
    assert agent._worst_funnel_stage(None) is None
    assert agent._worst_funnel_stage([]) is None


def test_rule_summary_reflects_only_real_fields():
    agent = AnalyticsAgent()
    out = agent._rule_summary({
        "available": True, "total_messages": 10, "total_contacts": 4,
        "total_appointments": 0, "conversion_rate": 0.0,
    })
    assert "10 messages" in out
    assert "4 contacts" in out
    assert "0.0%" in out
    # Missing keys must not fabricate lines
    minimal = agent._rule_summary({"available": True})
    assert "messages exchanged" not in minimal
