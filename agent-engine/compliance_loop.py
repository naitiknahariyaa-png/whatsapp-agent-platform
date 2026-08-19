"""
Compliance & Consent Loop — tracks opt-in per lead, processes consent events, auto-purge

Runs nightly to anonymize/delete data older than retention period.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field

from sqlalchemy import select, delete, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from db import Base, async_session
from config import settings
from logging_setup import get_logger

logger = get_logger("compliance_loop")


# ---------------------------------------------------------------------------
# DB Models
# ---------------------------------------------------------------------------

class ConsentRecordDB(Base):
    __tablename__ = "consent_records"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String(20), index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    consent_type: Mapped[str] = mapped_column(String(50))
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[Optional[str]] = mapped_column(String(50))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class DataRetentionLog(Base):
    __tablename__ = "data_retention_logs"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(50))  # anonymized, deleted
    target_table: Mapped[str] = mapped_column(String(50))
    records_affected: Mapped[int] = mapped_column(Integer, default=0)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    details: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Compliance Loop
# ---------------------------------------------------------------------------

class ConsentType(Enum):
    MARKETING = "marketing"
    COMMUNICATION = "communication"
    DATA_PROCESSING = "data_processing"
    THIRD_PARTY_SHARING = "third_party_sharing"
    ANALYTICS = "analytics"


class ComplianceLoop:
    """Tracks explicit opt-in per lead, processes consent events, auto-purge."""

    def __init__(self, retention_days: int = 365):
        self.retention_days = retention_days

    async def record_consent(self, phone_number: str, client_id: int,
                             consent_type: str, granted: bool,
                             source: str = "whatsapp") -> ConsentRecordDB:
        """Log a consent event."""
        async with async_session() as session:
            record = ConsentRecordDB(
                phone_number=phone_number,
                client_id=client_id,
                consent_type=consent_type,
                granted=granted,
                source=source,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)
            logger.info(f"[v] Consent recorded: {phone_number} {consent_type}={'granted' if granted else 'denied'} (source={source})")
            return record

    async def check_can_send(self, phone_number: str, client_id: int) -> bool:
        """Return False if opted out."""
        from services.compliance import compliance_manager
        if phone_number in compliance_manager.opt_out_records:
            return False

        async with async_session() as session:
            result = await session.execute(
                select(ConsentRecordDB).where(
                    ConsentRecordDB.phone_number == phone_number,
                    ConsentRecordDB.client_id == client_id,
                    ConsentRecordDB.consent_type == "marketing",
                ).order_by(ConsentRecordDB.recorded_at.desc()).limit(1)
            )
            record = result.scalar_one_or_none()
            if record and not record.granted:
                return False
        return True

    async def process_consent_events(self) -> Dict[str, int]:
        """Called periodically — handle pending consent changes."""
        stats = {"processed": 0, "opted_out": 0, "errors": 0}
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(ConsentRecordDB).where(ConsentRecordDB.granted == False)
                )
                denied = result.scalars().all()

                for record in denied:
                    try:
                        lead_funnel_instance = __import__("lead_funnel", fromlist=["LeadFunnel"]).lead_funnel
                        await lead_funnel_instance.on_opt_out(record.phone_number, record.client_id)
                        stats["opted_out"] += 1
                        stats["processed"] += 1
                    except Exception as e:
                        logger.error(f"Consent processing error for {record.phone_number}: {e}")
                        stats["errors"] += 1
        except Exception as e:
            logger.error(f"Consent event processing error: {e}")
            stats["errors"] += 1

        logger.info(f"[v] Consent events processed: {stats}")
        return stats

    async def auto_purge(self, retention_days: Optional[int] = None) -> Dict[str, int]:
        """Run nightly — anonymize or delete lead data older than retention period."""
        retention = retention_days or self.retention_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
        stats = {"anonymized": 0, "deleted": 0, "errors": 0}

        try:
            async with async_session() as session:
                from db import Message, Contact, Lead, Appointment
                from sqlalchemy import text

                cutoff_str = cutoff.isoformat()

                old_messages = await session.execute(
                    select(Message).where(Message.created_at < cutoff)
                )
                messages = old_messages.scalars().all()
                for msg in messages:
                    msg.content = "[ANONYMIZED]"
                    msg.phone_number = "0000000000"
                    stats["anonymized"] += 1

                old_contacts = await session.execute(
                    select(Contact).where(Contact.created_at < cutoff)
                )
                contacts = old_contacts.scalars().all()
                for contact in contacts:
                    contact.name = "Anonymized"
                    contact.email = None
                    contact.phone_number = "0000000000"
                    contact.notes = None
                    contact.custom_fields = {}
                    stats["anonymized"] += 1

                await session.commit()

                log = DataRetentionLog(
                    action="anonymized",
                    target_table="messages,contacts",
                    records_affected=stats["anonymized"],
                    details={"retention_days": retention, "cutoff": cutoff_str},
                )
                session.add(log)
                await session.commit()

        except Exception as e:
            logger.error(f"Auto-purge error: {e}")
            stats["errors"] += 1

        logger.info(f"[v] Auto-purge completed: {stats}")
        return stats

    async def get_consent_summary(self, client_id: Optional[int] = None) -> Dict:
        """Get consent statistics."""
        async with async_session() as session:
            query = select(ConsentRecordDB)
            if client_id:
                query = query.where(ConsentRecordDB.client_id == client_id)
            result = await session.execute(query)
            records = result.scalars().all()

            granted = sum(1 for r in records if r.granted)
            denied = sum(1 for r in records if not r.granted)
            by_type = {}
            for r in records:
                by_type[r.consent_type] = by_type.get(r.consent_type, {"granted": 0, "denied": 0})
                if r.granted:
                    by_type[r.consent_type]["granted"] += 1
                else:
                    by_type[r.consent_type]["denied"] += 1

            return {
                "total": len(records),
                "granted": granted,
                "denied": denied,
                "by_type": by_type,
            }


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

compliance_loop = ComplianceLoop()
