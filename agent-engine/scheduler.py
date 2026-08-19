import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

import httpx
from sqlalchemy import select, update, func
from db import async_session, Contact, Appointment, Conversation, Message, CompanyReport, QALog
from agents.sales import SalesAgent
from agents.manager import ManagerAgent
from agents.qa_agent import QAAgent
from llm_setup import get_llm

logger = logging.getLogger(\"scheduler\")

# Configuration
NUDGE_INTERVAL_HOURS = 4
NUDGE_STALE_HOURS = 24
MAX_NUDGES = 3
APPT_CHECK_INTERVAL_MINS = 15
REMINDER_WINDOW_HOURS = 24

class AutonomousWorkforce:
    def __init__(self):
        self.sales_agent = SalesAgent()
        self.manager = ManagerAgent()
        self.qa_agent = QAAgent()
        self.llm = get_llm()
        self._tasks = []

    async def _send_whatsapp(self, phone: str, message: str):
        try:
            from config import settings
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f\"{settings.whatsapp_bridge_url}/send\",
                    json={\"to\": phone, \"message\": message},
                    timeout=10
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error(f\"Outbound send failed for {phone}: {e}\")
            return False

    async def lead_nurture_loop(self):
        while True:
            try:
                logger.info(\"Running Lead Nurture Loop...\")
                async with async_session() as session:
                    stale_time = datetime.now(timezone.utc) - timedelta(hours=NUDGE_STALE_HOURS)
                    result = await session.execute(
                        select(Contact).where(
                            Contact.lead_status == \"contacted\",
                            Contact.updated_at < stale_time
                        )
                    )
                    leads = result.scalars().all()

                    for lead in leads:
                        history = await self._get_recent_messages(session, lead.phone_number)
                        if any(word in history.lower() for word in [\"stop\", \"unsubscribe\", \"opt out\"]):
                            lead.lead_status = \"unsubscribed\"
                            continue

                        fields = lead.custom_fields or {}
                        nudge_count = fields.get(\"nudge_count\", 0)
                        if nudge_count >= MAX_NUDGES:
                            lead.lead_status = \"cold\"
                            continue

                        if await self._has_user_replied_recently(session, lead.phone_number):
                            continue

                        nudge_prompt = (
                            f\"Lead {lead.name} ({lead.phone_number}) is stale. \"
                            f\"Known facts: {json.dumps(fields)}. \"
                            \"Generate a short, friendly, personalized nudge to restart the conversation.\"
                        )
                        nudge_msg = await self.sales_agent.run(nudge_prompt)

                        if await self._send_whatsapp(lead.phone_number, nudge_msg):
                            fields[\"nudge_count\"] = nudge_count + 1
                            lead.custom_fields = fields
                            lead.updated_at = datetime.now(timezone.utc)
                    await session.commit()
            except Exception as e:
                logger.error(f\"Lead Nurture Loop error: {e}\", exc_info=True)
            await asyncio.sleep(NUDGE_INTERVAL_HOURS * 3600)

    async def _get_recent_messages(self, session, phone: str) -> str:
        res = await session.execute(
            select(Message).where(Message.phone_number == phone).order_by(Message.created_at.desc()).limit(5)
        )
        msgs = res.scalars().all()
        return \" \".join([m.content or \"\" for m in msgs])

    async def _has_user_replied_recently(self, session, phone: str) -> bool:
        res = await session.execute(
            select(Message).where(Message.phone_number == phone).order_by(Message.created_at.desc()).limit(1)
        )
        last = res.scalar_one_or_none()
        return last and last.direction == \"incoming\"

    async def appointment_guard_loop(self):
        while True:
            try:
                logger.info(\"Running Appointment Guard Loop...\")
                now = datetime.now(timezone.utc)
                async with async_session() as session:
                    tomorrow = (now + timedelta(hours=REMINDER_WINDOW_HOURS)).strftime(\"%Y-%m-%d\")
                    result = await session.execute(
                        select(Appointment).where(
                            Appointment.status == \"scheduled\",
                            Appointment.appointment_date == tomorrow.split('T')[0]
                        )
                    )
                    for appt in result.scalars().all():
                        await self._send_whatsapp(appt.phone_number, f\"Reminder: {appt.title} at {appt.appointment_time} tomorrow!\")

                    today_str = now.strftime(\"%Y-%m-%d\")
                    past_appts = await session.execute(
                        select(Appointment).where(
                            Appointment.appointment_date == today_str,
                            Appointment.status == \"scheduled\"
                        )
                    )
                    for appt in past_appts.scalars():
                        appt_time = datetime.strptime(appt.appointment_time, \"%H:%M\").replace(
                            year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc
                        )
                        if now > appt_time + timedelta(minutes=30):
                            appt.status = \"no-show\"
                            await self._send_whatsapp(appt.phone_number, \"We missed you! Want to reschedule?\")
                    await session.commit()
            except Exception as e:
                logger.error(f\"Appointment Guard Loop error: {e}\", exc_info=True)
            await asyncio.sleep(APPT_CHECK_INTERVAL_MINS * 60)

    async def weekly_ceo_report(self):
        while True:
            now = datetime.now(timezone.utc)
            if now.weekday() == 6 and now.hour == 23 and now.minute == 0:
                try:
                    logger.info(\"Generating Weekly CEO Report...\")
                    async with async_session() as session:
                        last_week = now - timedelta(days=7)
                        lead_count = (await session.execute(select(func.count(Contact.id)).where(Contact.created_at > last_week))).scalar()
                        msg_count = (await session.execute(select(func.count(Message.id)).where(Message.created_at > last_week))).scalar()
                        conv_count = (await session.execute(select(func.count(Contact.id)).where(Contact.lead_status == \"converted\", Contact.created_at > last_week))).scalar()
                        conv_rate = (conv_count / lead_count * 100) if lead_count > 0 else 0
                        
                        metrics = {\"total_leads\": lead_count, \"total_messages\": msg_count, \"conversion_rate\": f\"{round(conv_rate, 2)}%\"}
                        
                        res = await session.execute(select(Message.content).where(Message.direction == \"incoming\", Message.created_at > last_week).limit(100))
                        logs = \"\\n\".join([r[0] for r in res.all() if r[0]])
                        
                        summary_prompt = f\"Analyze these logs and identify: Most asked question, Top drop-off point, and General sentiment. Logs:\\n{logs}\"
                        summary = await self.llm.ainvoke([{\"role\": \"user\", \"content\": summary_prompt}])
                        summary_text = summary.content if hasattr(summary, 'content') else str(summary)
                        
                        report = CompanyReport(client_id=1, metrics=metrics, summary=summary_text, drop_off_point=\"Analyzed in summary\")
                        session.add(report)
                        await session.commit()
                        await self._send_whatsapp(\"OWNER_PHONE_NUMBER\", f\"📊 Weekly Report:\\n\\n{json.dumps(metrics, indent=2)}\\n\\nAnalysis:\\n{summary_text}\")
                except Exception as e:
                    logger.error(f\"Weekly Report error: {e}\", exc_info=True)
            await asyncio.sleep(3600)

    async def quality_assurance_loop(self):
        \"\"\"
        Sample a random % of conversations and have the QAAgent grade them.
        Catches silent regressions in tone and accuracy.
        \"\"\"
        while True:
            now = datetime.now(timezone.utc)
            if now.weekday() == 0 and now.hour == 1 and now.minute == 0:
                try:
                    logger.info(\"Running QA Conversation Grading...\")
                    async with async_session() as session:
                        res = await session.execute(select(Conversation).limit(50))
                        convs = res.scalars().all()
                        
                        for conv in convs:
                            history_res = await session.execute(
                                select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
                            )
                            msgs = history_res.scalars().all()
                            history_text = \"\\n\".join([f\"{m.direction}: {m.content}\" for m in msgs])
                            
                            # Use the specialized QAAgent
                            grade_data = await self.qa_agent.grade_conversation(history_text)
                            
                            from db import QALog
                            qa_log = QALog(
                                conversation_id=conv.id,
                                client_id=conv.client_id,
                                grade=grade_data.get(\"grade\", 0.0),
                                feedback=grade_data.get(\"feedback\", \"\"),
                                rag_used_correctly=grade_data.get(\"rag_correct\", True),
                                escalation_missed=grade_data.get(\"escalation_missed\", False)
                            )
                            session.add(qa_log)
                        await session.commit()
                except Exception as e:
                    logger.error(f\"QA Loop error: {e}\", exc_info=True)
            await asyncio.sleep(3600)

    async def start(self):
        self._tasks = [
            asyncio.create_task(self.lead_nurture_loop()),
            asyncio.create_task(self.appointment_guard_loop()),
            asyncio.create_task(self.weekly_ceo_report()),
            asyncio.create_task(self.quality_assurance_loop())
        ]
        logger.info(\"🚀 Autonomous Workforce started: Nurture, Guard, CEO Report, and QA loops are active.\")

    async def stop(self):
        for t in self._tasks: t.cancel()
        logger.info(\"Autonomous Workforce stopped.\")
