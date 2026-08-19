"""
Drip Campaign Builder — Sequence-based messaging with delays, triggers, and conditions
"""
import asyncio
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger("drip_campaigns")


class TriggerType(Enum):
    """What triggers a campaign enrollment"""
    TAG_ADDED = "tag_added"
    LEAD_CREATED = "lead_created"
    APPOINTMENT_BOOKED = "appointment_booked"
    PURCHASE_MADE = "purchase_made"
    CUSTOM_EVENT = "custom_event"
    MANUAL = "manual"
    SCHEDULED = "scheduled"  # e.g. birthday, anniversary


class ActionType(Enum):
    """What a campaign step does"""
    SEND_MESSAGE = "send_message"
    WAIT_DURATION = "wait_duration"
    WAIT_UNTIL = "wait_until"
    CONDITIONAL_SPLIT = "conditional_split"
    UPDATE_TAG = "update_tag"
    UPDATE_LEAD_SCORE = "update_lead_score"
    WEBHOOK = "webhook"
    API_CALL = "api_call"
    ADD_TO_CAMPAIGN = "add_to_campaign"


@dataclass
class CampaignStep:
    """A single step in a campaign sequence"""
    id: str
    action: ActionType
    config: Dict[str, Any] = field(default_factory=dict)
    children: List[str] = field(default_factory=list)  # next step IDs

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action": self.action.value,
            "config": self.config,
            "children": self.children,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CampaignStep":
        return cls(
            id=data["id"],
            action=ActionType(data["action"]),
            config=data.get("config", {}),
            children=data.get("children", []),
        )


@dataclass
class DripCampaign:
    """A complete drip campaign definition"""
    id: str
    name: str
    description: str = ""
    trigger: TriggerType = TriggerType.MANUAL
    trigger_config: Dict[str, Any] = field(default_factory=dict)
    steps: Dict[str, CampaignStep] = field(default_factory=dict)
    root_step_id: Optional[str] = None
    tags_to_add: List[str] = field(default_factory=list)
    tags_to_remove: List[str] = field(default_factory=list)
    client_id: int = 1
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger": self.trigger.value,
            "trigger_config": self.trigger_config,
            "steps": {k: v.to_dict() for k, v in self.steps.items()},
            "root_step_id": self.root_step_id,
            "tags_to_add": self.tags_to_add,
            "tags_to_remove": self.tags_to_remove,
            "client_id": self.client_id,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DripCampaign":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            trigger=TriggerType(data["trigger"]),
            trigger_config=data.get("trigger_config", {}),
            steps={k: CampaignStep.from_dict(v) for k, v in data.get("steps", {}).items()},
            root_step_id=data.get("root_step_id"),
            tags_to_add=data.get("tags_to_add", []),
            tags_to_remove=data.get("tags_to_remove", []),
            client_id=data.get("client_id", 1),
            is_active=data.get("is_active", True),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


class CampaignEnrollment:
    """Tracks a contact's progress through a campaign"""

    def __init__(self, campaign_id: str, contact_id: str, channel: str = "whatsapp"):
        self.campaign_id = campaign_id
        self.contact_id = contact_id
        self.channel = channel
        self.current_step_id: Optional[str] = None
        self.completed_step_ids: List[str] = []
        self.status = "active"  # active, paused, completed, removed
        self.enrolled_at = datetime.utcnow().isoformat()
        self.last_step_at: Optional[str] = None
        self.metadata: Dict[str, Any] = {}

    def to_dict(self) -> Dict:
        return {
            "campaign_id": self.campaign_id,
            "contact_id": self.contact_id,
            "channel": self.channel,
            "current_step_id": self.current_step_id,
            "completed_step_ids": self.completed_step_ids,
            "status": self.status,
            "enrolled_at": self.enrolled_at,
            "last_step_at": self.last_step_at,
            "metadata": self.metadata,
        }


class DripCampaignEngine:
    """
    Engine that processes drip campaigns — evaluates triggers, 
    executes steps, handles delays and conditions.
    """

    def __init__(self):
        self.campaigns: Dict[str, DripCampaign] = {}
        self.enrollments: Dict[str, CampaignEnrollment] = {}  # key: f"{campaign_id}_{contact_id}"
        self.message_sender = None  # Async callable: (channel, contact_id, content) -> bool
        self._running = False
        self._process_task = None

    def register_campaign(self, campaign: DripCampaign):
        """Register a new campaign"""
        self.campaigns[campaign.id] = campaign
        logger.info(f"[+] Campaign registered: {campaign.name} ({campaign.id})")

    def remove_campaign(self, campaign_id: str):
        """Remove a campaign"""
        self.campaigns.pop(campaign_id, None)
        # Remove all enrollments for this campaign
        self.enrollments = {
            k: v for k, v in self.enrollments.items()
            if v.campaign_id != campaign_id
        }

    async def enroll(self, campaign_id: str, contact_id: str, channel: str = "whatsapp",
                     metadata: Optional[Dict] = None) -> Optional[str]:
        """Enroll a contact in a campaign"""
        campaign = self.campaigns.get(campaign_id)
        if not campaign or not campaign.is_active:
            logger.warning(f"Cannot enroll: campaign {campaign_id} not found/inactive")
            return None

        if not campaign.root_step_id:
            logger.warning(f"Campaign {campaign_id} has no root step")
            return None

        key = f"{campaign_id}_{contact_id}"
        if key in self.enrollments:
            logger.info(f"Contact {contact_id} already enrolled in {campaign_id}, skipping")
            return key

        enrollment = CampaignEnrollment(campaign_id, contact_id, channel)
        enrollment.current_step_id = campaign.root_step_id
        enrollment.metadata = metadata or {}
        self.enrollments[key] = enrollment
        logger.info(f"[v] Enrolled {contact_id} in campaign {campaign.name}")
        return key

    async def unenroll(self, campaign_id: str, contact_id: str):
        """Remove a contact from a campaign"""
        key = f"{campaign_id}_{contact_id}"
        self.enrollments.pop(key, None)

    async def _execute_step(self, enrollment: CampaignEnrollment):
        """Execute a single campaign step"""
        campaign = self.campaigns.get(enrollment.campaign_id)
        if not campaign or not campaign.is_active:
            return

        step = campaign.steps.get(enrollment.current_step_id)
        if not step:
            enrollment.status = "completed"
            return

        logger.debug(f"Executing step {step.id} ({step.action.value}) for {enrollment.contact_id}")

        if step.action == ActionType.SEND_MESSAGE:
            content = step.config.get("content", "")
            channel = step.config.get("channel", enrollment.channel)
            if self.message_sender and enrollment.status == "active":
                await self.message_sender(channel, enrollment.contact_id, content)

        elif step.action == ActionType.WAIT_DURATION:
            seconds = step.config.get("seconds", 3600)
            await asyncio.sleep(seconds)

        elif step.action == ActionType.WAIT_UNTIL:
            target_time_str = step.config.get("target_time", "")
            if target_time_str:
                target_time = datetime.fromisoformat(target_time_str)
                now = datetime.utcnow()
                if target_time > now:
                    wait_seconds = (target_time - now).total_seconds()
                    await asyncio.sleep(min(wait_seconds, 86400))  # max 1 day per tick

        elif step.action == ActionType.UPDATE_TAG:
            tag = step.config.get("tag", "")
            if tag and enrollment.contact_id:
                logger.info(f"Would add tag '{tag}' to {enrollment.contact_id}")

        elif step.action == ActionType.UPDATE_LEAD_SCORE:
            score_delta = step.config.get("score_delta", 0)
            logger.info(f"Would update lead score by {score_delta} for {enrollment.contact_id}")

        elif step.action == ActionType.WEBHOOK:
            url = step.config.get("url", "")
            payload = step.config.get("payload", {})
            if url:
                try:
                    import httpx
                    async with httpx.AsyncClient() as client:
                        await client.post(url, json=payload, timeout=10)
                except Exception as e:
                    logger.error(f"Webhook failed for step {step.id}: {e}")

        # Mark step as completed
        enrollment.completed_step_ids.append(step.id)
        enrollment.last_step_at = datetime.utcnow().isoformat()

        # Move to next step
        if step.children:
            enrollment.current_step_id = step.children[0]
        else:
            enrollment.status = "completed"

    async def process_enrollments(self):
        """Process all active enrollments — called periodically via ARQ"""
        from arq_worker import enqueue_job
        for key, enrollment in list(self.enrollments.items()):
            if enrollment.status != "active":
                continue
            try:
                await enqueue_job("process_drip_step", key, enrollment.current_step_id)
            except Exception as e:
                logger.error(f"Error enqueuing enrollment {key}: {e}")
                enrollment.status = "paused"

    async def start(self, interval: float = 5.0):
        """Start the campaign processing loop via ARQ."""
        self._running = True
        try:
            from arq_worker import enqueue_job
            await enqueue_job("process_drip_enrollments")
            logger.info("[v] Drip campaign engine started via ARQ")
        except Exception as e:
            logger.error(f"[!] Failed to start drip engine via ARQ: {e}")

    async def stop(self):
        """Stop the campaign engine"""
        self._running = False

    def get_enrollment(self, campaign_id: str, contact_id: str) -> Optional[CampaignEnrollment]:
        """Get a specific enrollment"""
        return self.enrollments.get(f"{campaign_id}_{contact_id}")

    def get_campaign_stats(self, campaign_id: str) -> Dict:
        """Get statistics for a campaign"""
        campaign = self.campaigns.get(campaign_id)
        if not campaign:
            return {}

        enrollments = [
            e for e in self.enrollments.values()
            if e.campaign_id == campaign_id
        ]
        return {
            "campaign_id": campaign_id,
            "name": campaign.name,
            "total_enrolled": len(enrollments),
            "active": sum(1 for e in enrollments if e.status == "active"),
            "completed": sum(1 for e in enrollments if e.status == "completed"),
            "paused": sum(1 for e in enrollments if e.status == "paused"),
        }


# Global engine instance
engine = DripCampaignEngine()


async def process_drip_enrollments(ctx: dict):
    """ARQ task: process enrollments and re-enqueue itself."""
    if not engine._running:
        return
    try:
        await engine.process_enrollments()
    except Exception as e:
        logger.error(f"Campaign engine ARQ error: {e}")
    if engine._running:
        try:
            from arq_worker import enqueue_job
            await enqueue_job("process_drip_enrollments", _defer_until=datetime.utcnow() + timedelta(seconds=5))
        except Exception as e:
            logger.error(f"Failed to re-enqueue drip processing: {e}")