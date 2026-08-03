"""
Lead Generation Agent — Meta Click-to-WhatsApp Ads integration
Qualifies leads from FB/IG ads, stores in CRM with pipeline status.
"""
import os
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, Integer, DateTime, JSON

from db import Base, async_session


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[Optional[str]] = mapped_column(String(50))  # facebook, instagram, direct
    campaign_id: Mapped[Optional[str]] = mapped_column(String(100))
    ad_id: Mapped[Optional[str]] = mapped_column(String(100))
    budget: Mapped[Optional[str]] = mapped_column(String(50))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    requirement: Mapped[Optional[str]] = mapped_column(Text)
    lead_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="new")  # new, qualified, contacted, converted, lost
    qualification_data: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class LeadGenAgent:
    """Qualifies leads from Meta Click-to-WhatsApp Ads"""

    def __init__(self):
        self.qualifying_questions = [
            "May I know your name?",
            "What is your budget?",
            "Which city/location are you from?",
            "What exactly are you looking for?"
        ]

    async def receive_meta_webhook(self, payload: Dict[str, Any]) -> Dict:
        """Receive Meta webhook for Click-to-WhatsApp Ad leads"""
        try:
            entry = payload.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            field = changes.get("field", "")
            value = changes.get("value", {})

            if field == "messages":
                # Extract lead info from Meta ad
                contact = value.get("contacts", [{}])[0]
                phone = contact.get("wa_id", "").replace("91", "", 1) if contact.get("wa_id", "").startswith("91") else contact.get("wa_id", "")
                name = contact.get("profile", {}).get("name", "")
                context = value.get("context", {})
                ad_id = context.get("ad_id", "")
                campaign_id = context.get("campaign_id", "")

                # Store lead
                lead = await self.create_lead(
                    phone_number=phone,
                    name=name,
                    source="meta_ad",
                    campaign_id=campaign_id,
                    ad_id=ad_id
                )

                return {"status": "lead_created", "lead_id": lead.id, "phone": phone}

            return {"status": "ignored", "reason": "not a lead message"}

        except Exception as e:
            return {"error": str(e)}

    async def create_lead(self, phone_number: str, name: str = "", source: str = "direct",
                          campaign_id: str = "", ad_id: str = "", **kwargs) -> Lead:
        """Create or update a lead in CRM"""
        async with async_session() as session:
            existing = await session.execute(
                select(Lead).where(Lead.phone_number == phone_number)
            )
            lead = existing.scalar_one_or_none()

            if lead:
                if name:
                    lead.name = name
                if source:
                    lead.source = source
                lead.updated_at = datetime.now(timezone.utc)
            else:
                lead = Lead(
                    phone_number=phone_number,
                    name=name,
                    source=source,
                    campaign_id=campaign_id,
                    ad_id=ad_id,
                    **kwargs
                )
                session.add(lead)

            await session.commit()
            await session.refresh(lead)
            return lead

    async def qualify_lead(self, phone_number: str, message: str, entities: Dict) -> Dict:
        """Qualify a lead based on extracted entities from conversation"""
        async with async_session() as session:
            result = await session.execute(
                select(Lead).where(Lead.phone_number == phone_number)
            )
            lead = result.scalar_one_or_none()

            if not lead:
                lead = await self.create_lead(phone_number=phone_number, source="whatsapp")

            # Update lead with extracted info
            updated = False
            if entities.get("person_name") and not lead.name:
                lead.name = entities["person_name"]
                updated = True
            if entities.get("location"):
                lead.location = entities["location"]
                updated = True
            if entities.get("budget"):
                lead.budget = entities["budget"]
                updated = True
            if entities.get("product_name"):
                lead.requirement = entities["product_name"]
                updated = True

            # Calculate lead score (0-100)
            score = 0
            if lead.name:
                score += 20
            if lead.location:
                score += 20
            if lead.budget:
                score += 30
            if lead.requirement:
                score += 30

            lead.lead_score = score

            # Update status based on score
            if score >= 80:
                lead.status = "qualified"
            elif score >= 40:
                lead.status = "contacted"
            else:
                lead.status = "new"

            lead.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return {
                "lead_id": lead.id,
                "score": score,
                "status": lead.status,
                "name": lead.name,
                "next_question": self._get_next_question(lead)
            }

    def _get_next_question(self, lead: Lead) -> Optional[str]:
        """Get the next qualifying question for the lead"""
        if not lead.name:
            return "May I know your name? 🙏"
        if not lead.location:
            return "Which city are you from? 📍"
        if not lead.budget:
            return "What is your budget? 💰"
        if not lead.requirement:
            return "What exactly are you looking for? 🎯"
        return None  # Lead fully qualified

    async def get_leads(self, status: str = "") -> List[Dict]:
        """Get all leads, optionally filtered by status"""
        async with async_session() as session:
            if status:
                result = await session.execute(
                    select(Lead).where(Lead.status == status).order_by(Lead.created_at.desc())
                )
            else:
                result = await session.execute(
                    select(Lead).order_by(Lead.created_at.desc())
                )
            leads = result.scalars().all()
            return [{
                "id": l.id,
                "phone": l.phone_number,
                "name": l.name,
                "source": l.source,
                "score": l.lead_score,
                "status": l.status,
                "budget": l.budget,
                "location": l.location,
                "requirement": l.requirement,
                "created_at": l.created_at.isoformat() if l.created_at else None
            } for l in leads]

    async def update_lead_status(self, lead_id: int, status: str) -> Dict:
        """Update lead status (new → qualified → contacted → converted/lost)"""
        valid = ["new", "qualified", "contacted", "converted", "lost"]
        if status not in valid:
            return {"error": f"Invalid status. Options: {valid}"}

        async with async_session() as session:
            result = await session.execute(select(Lead).where(Lead.id == lead_id))
            lead = result.scalar_one_or_none()
            if not lead:
                return {"error": "Lead not found"}

            lead.status = status
            lead.updated_at = datetime.now(timezone.utc)
            await session.commit()

            return {"status": "updated", "lead_id": lead_id, "new_status": status}


# Global instance
lead_gen_agent = LeadGenAgent()