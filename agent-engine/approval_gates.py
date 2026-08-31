"""
Human-in-the-Loop Approval Gates
================================

For high-stakes actions (large invoices, refunds, legal commitments),
require human approval via dashboard/WhatsApp before execution.

Features:
- Configurable approval thresholds per action type
- Multi-channel approval (dashboard, WhatsApp, email)
- Timeout handling with escalation
- Audit trail of all approvals/rejections
- Role-based approvers
"""
import os
import uuid
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# DB-backed persistence for approval requests (falls back to in-memory on failure).
from db import Base, async_session
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Integer, Float, JSON

logger = logging.getLogger("approval_gates")


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalChannel(Enum):
    DASHBOARD = "dashboard"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SLACK = "slack"


class ActionRisk(Enum):
    LOW = "low"           # Auto-approve
    MEDIUM = "medium"     # Single approver
    HIGH = "high"         # Multiple approvers
    CRITICAL = "critical" # Senior approver + audit


@dataclass
class ApprovalRule:
    """Rule defining when approval is required."""
    action_type: str                      # e.g., "refund", "invoice", "legal_commitment"
    risk_level: ActionRisk
    amount_threshold: Optional[float] = None  # If applicable
    required_approvers: int = 1
    approver_roles: List[str] = field(default_factory=list)  # e.g., ["manager", "admin"]
    timeout_minutes: int = 60
    escalation_roles: List[str] = field(default_factory=list)
    channels: List[ApprovalChannel] = field(default_factory=lambda: [ApprovalChannel.DASHBOARD])


@dataclass
class ApprovalRequest:
    """An approval request waiting for human decision."""
    id: str
    action_type: str
    requester_id: str                    # User/agent who requested
    client_id: int
    conversation_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)  # Action details
    amount: Optional[float] = None
    risk_level: ActionRisk = ActionRisk.MEDIUM
    status: ApprovalStatus = ApprovalStatus.PENDING
    required_approvers: int = 1
    approver_roles: List[str] = field(default_factory=list)
    approvals: List[Dict[str, Any]] = field(default_factory=list)  # [{"user_id", "role", "decision", "timestamp", "comment"}]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: Optional[str] = None
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    channel: ApprovalChannel = ApprovalChannel.DASHBOARD
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalDecision:
    """A single approval/rejection decision."""
    request_id: str
    approver_id: str
    approver_role: str
    decision: ApprovalStatus  # APPROVED or REJECTED
    comment: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ─── DB persistence model ──────────────────────────────────────────────
# Mirrors the ApprovalRequest dataclass so requests survive restarts.

class ApprovalRequestDB(Base):
    """Durable copy of an approval request."""
    __tablename__ = "approval_requests"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    action_type: Mapped[str] = mapped_column(String(100), index=True)
    requester_id: Mapped[str] = mapped_column(String(128), index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    amount: Mapped[Optional[float]] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    required_approvers: Mapped[int] = mapped_column(Integer, default=1)
    approver_roles: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    approvals: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[Optional[str]] = mapped_column(String(40))
    decided_at: Mapped[Optional[str]] = mapped_column(String(40))
    decided_by: Mapped[Optional[str]] = mapped_column(String(128))
    channel: Mapped[Optional[str]] = mapped_column(String(20), default="dashboard")
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)


def _row_to_approval(row: ApprovalRequestDB) -> "ApprovalRequest":
    """Rebuild an ApprovalRequest dataclass from a DB row."""
    def _enum(enum_cls, val, default):
        try:
            return enum_cls(val) if val else default
        except Exception:
            return default
    return ApprovalRequest(
        id=row.id,
        action_type=row.action_type,
        requester_id=row.requester_id,
        client_id=row.client_id,
        conversation_id=row.conversation_id,
        payload=dict(row.payload) if row.payload else {},
        amount=row.amount,
        risk_level=_enum(ActionRisk, row.risk_level, ActionRisk.MEDIUM),
        status=_enum(ApprovalStatus, row.status, ApprovalStatus.PENDING),
        required_approvers=row.required_approvers,
        approver_roles=list(row.approver_roles) if row.approver_roles else [],
        approvals=list(row.approvals) if row.approvals else [],
        created_at=row.created_at,
        expires_at=row.expires_at,
        decided_at=row.decided_at,
        decided_by=row.decided_by,
        channel=_enum(ApprovalChannel, row.channel, ApprovalChannel.DASHBOARD),
        metadata=dict(row.extra_metadata) if row.extra_metadata else {},
    )


async def _save_approval_db(request: "ApprovalRequest") -> bool:
    """Persist an ApprovalRequest to the DB. Returns False on any failure."""
    try:
        async with async_session() as session:
            row = await session.get(ApprovalRequestDB, request.id)
            if row is None:
                row = ApprovalRequestDB(id=request.id)
                session.add(row)
            row.action_type = request.action_type
            row.requester_id = request.requester_id
            row.client_id = request.client_id
            row.conversation_id = request.conversation_id
            row.payload = request.payload or {}
            row.amount = request.amount
            row.risk_level = request.risk_level.value if request.risk_level else "medium"
            row.status = request.status.value if request.status else "pending"
            row.required_approvers = request.required_approvers
            row.approver_roles = request.approver_roles or []
            row.approvals = request.approvals or []
            row.created_at = request.created_at or datetime.utcnow().isoformat()
            row.expires_at = request.expires_at
            row.decided_at = request.decided_at
            row.decided_by = request.decided_by
            row.channel = request.channel.value if request.channel else "dashboard"
            row.extra_metadata = request.metadata or {}
            await session.commit()
        return True
    except Exception as e:
        logger.warning("Could not persist approval request %s: %s", request.id, e)
        return False


async def _load_approval_db(request_id: str) -> Optional["ApprovalRequest"]:
    """Load an ApprovalRequest from the DB by id, or None."""
    try:
        async with async_session() as session:
            row = await session.get(ApprovalRequestDB, request_id)
            return None if row is None else _row_to_approval(row)
    except Exception as e:
        logger.warning("Could not load approval request %s: %s", request_id, e)
        return None


async def _list_pending_db(client_id: Optional[int] = None) -> List["ApprovalRequest"]:
    """List pending approval requests from the DB, optionally scoped to a tenant."""
    try:
        from sqlalchemy import select
        async with async_session() as session:
            q = select(ApprovalRequestDB).where(ApprovalRequestDB.status == "pending")
            if client_id is not None:
                q = q.where(ApprovalRequestDB.client_id == int(client_id))
            rows = (await session.execute(q)).scalars().all()
            return [_row_to_approval(r) for r in rows]
    except Exception as e:
        logger.warning("Could not list pending approvals: %s", e)
        return []


# ─── Default Approval Rules ────────────────────────────────────────

DEFAULT_APPROVAL_RULES = {
    "refund": ApprovalRule(
        action_type="refund",
        risk_level=ActionRisk.HIGH,
        amount_threshold=1000.0,
        required_approvers=2,
        approver_roles=["manager", "admin"],
        timeout_minutes=30,
        escalation_roles=["admin"],
        channels=[ApprovalChannel.DASHBOARD, ApprovalChannel.WHATSAPP],
    ),
    "large_invoice": ApprovalRule(
        action_type="invoice",
        risk_level=ActionRisk.HIGH,
        amount_threshold=50000.0,
        required_approvers=2,
        approver_roles=["manager", "finance", "admin"],
        timeout_minutes=60,
        escalation_roles=["admin"],
        channels=[ApprovalChannel.DASHBOARD, ApprovalChannel.EMAIL],
    ),
    "legal_commitment": ApprovalRule(
        action_type="legal_commitment",
        risk_level=ActionRisk.CRITICAL,
        required_approvers=2,
        approver_roles=["legal", "admin"],
        timeout_minutes=120,
        escalation_roles=["admin", "legal"],
        channels=[ApprovalChannel.DASHBOARD, ApprovalChannel.EMAIL],
    ),
    "bulk_message": ApprovalRule(
        action_type="bulk_message",
        risk_level=ActionRisk.MEDIUM,
        amount_threshold=100,  # number of recipients
        required_approvers=1,
        approver_roles=["manager", "admin"],
        timeout_minutes=15,
        channels=[ApprovalChannel.DASHBOARD],
    ),
    "data_export": ApprovalRule(
        action_type="data_export",
        risk_level=ActionRisk.HIGH,
        required_approvers=1,
        approver_roles=["admin", "compliance"],
        timeout_minutes=30,
        channels=[ApprovalChannel.DASHBOARD],
    ),
    "account_deletion": ApprovalRule(
        action_type="account_deletion",
        risk_level=ActionRisk.CRITICAL,
        required_approvers=2,
        approver_roles=["admin"],
        timeout_minutes=60,
        escalation_roles=["admin"],
        channels=[ApprovalChannel.DASHBOARD, ApprovalChannel.EMAIL],
    ),
}


class ApprovalEngine:
    """
    Manages approval requests, routing, timeouts, and decisions.
    """

    def __init__(self, rules: Optional[Dict[str, ApprovalRule]] = None, use_db: bool = True):
        self.rules = rules or DEFAULT_APPROVAL_RULES.copy()
        self.use_db = use_db and True
        self._pending: Dict[str, ApprovalRequest] = {}
        self._timeouts: Dict[str, asyncio.Task] = {}
        self._handlers: Dict[ApprovalChannel, Callable] = {}
        self._stats = {"created": 0, "approved": 0, "rejected": 0, "expired": 0}

    def register_channel_handler(self, channel: ApprovalChannel, handler: Callable):
        """Register a handler for sending approval requests via a channel."""
        self._handlers[channel] = handler

    def get_rule(self, action_type: str) -> Optional[ApprovalRule]:
        return self.rules.get(action_type)

    def check_requires_approval(self, action_type: str, amount: float = None, context: Dict = None) -> Optional[ApprovalRule]:
        """Check if an action requires approval based on rules."""
        rule = self.rules.get(action_type)
        if not rule:
            return None

        if rule.amount_threshold is not None and amount is not None:
            if amount < rule.amount_threshold:
                return None

        return rule

    async def request_approval(
        self,
        action_type: str,
        requester_id: str,
        client_id: int,
        payload: Dict[str, Any],
        amount: float = None,
        conversation_id: str = None,
        custom_rule: ApprovalRule = None,
    ) -> ApprovalRequest:
        """Create and dispatch an approval request."""
        rule = custom_rule or self.check_requires_approval(action_type, amount)
        if not rule:
            # No approval needed
            return ApprovalRequest(
                id=str(uuid.uuid4()),
                action_type=action_type,
                requester_id=requester_id,
                client_id=client_id,
                payload=payload,
                amount=amount,
                status=ApprovalStatus.APPROVED,
                risk_level=ActionRisk.LOW,
            )

        request = ApprovalRequest(
            id=str(uuid.uuid4()),
            action_type=action_type,
            requester_id=requester_id,
            client_id=client_id,
            conversation_id=conversation_id,
            payload=payload,
            amount=amount,
            risk_level=rule.risk_level,
            required_approvers=rule.required_approvers,
            approver_roles=rule.approver_roles,
            expires_at=(datetime.utcnow() + timedelta(minutes=rule.timeout_minutes)).isoformat(),
            channel=rule.channels[0] if rule.channels else ApprovalChannel.DASHBOARD,
        )

        self._pending[request.id] = request
        self._stats["created"] += 1

        # Persist to DB (durable across restarts); non-fatal on failure
        await self._persist(request)

        # Send notifications via configured channels
        await self._notify_approvers(request, rule)

        # Set timeout
        timeout_task = asyncio.create_task(self._handle_timeout(request.id, rule.timeout_minutes * 60))
        self._timeouts[request.id] = timeout_task

        logger.info("Approval requested: %s (%s) for %s", request.id, action_type, requester_id)
        return request

    async def _notify_approvers(self, request: ApprovalRequest, rule: ApprovalRule):
        """Send approval request notifications via configured channels."""
        for channel in rule.channels:
            handler = self._handlers.get(channel)
            if handler:
                try:
                    await handler(request, rule)
                except Exception as e:
                    logger.error("Failed to send approval via %s: %s", channel.value, e)

    async def _persist(self, request: ApprovalRequest):
        """Persist a request to the DB so it survives restarts (failures are non-fatal)."""
        if not self.use_db:
            return
        await _save_approval_db(request)

    async def _handle_timeout(self, request_id: str, timeout_seconds: int):
        """Handle approval timeout."""
        await asyncio.sleep(timeout_seconds)
        request = self._pending.get(request_id)
        if request and request.status == ApprovalStatus.PENDING:
            request.status = ApprovalStatus.EXPIRED
            logger.warning("Approval request %s expired", request_id)
            self._stats["expired"] += 1
            await self._persist(request)
            # Notify requester of expiry
            await self._notify_expiry(request)

    async def _notify_expiry(self, request: ApprovalRequest):
        """Notify requester that approval expired."""
        pass  # Implement based on channel handlers

    async def decide(self, request_id: str, approver_id: str, approver_role: str,
                     decision: ApprovalStatus, comment: str = "") -> bool:
        """Record an approval/rejection decision."""
        request = self._pending.get(request_id)
        if request is None:
            # Hydrate from DB after a restart so in-flight requests remain decidable.
            request = await _load_approval_db(request_id)
            if request is None:
                return False
            self._pending[request_id] = request

        if request.status != ApprovalStatus.PENDING:
            return False

        # Check if approver has required role
        if request.approver_roles and approver_role not in request.approver_roles:
            logger.warning("Approver %s lacks required role for %s", approver_id, request_id)
            return False

        # Check for duplicate approval from same user
        for existing in request.approvals:
            if existing.get("user_id") == approver_id:
                return False

        approval = {
            "user_id": approver_id,
            "role": approver_role,
            "decision": decision.value,
            "comment": comment,
            "timestamp": datetime.utcnow().isoformat(),
        }
        request.approvals.append(approval)

        # Persist every vote so partial approvals survive restarts
        await self._persist(request)

        # Check if we have enough approvals
        if decision == ApprovalStatus.APPROVED:
            approved_count = sum(1 for a in request.approvals if a["decision"] == "approved")
            if approved_count >= request.required_approvers:
                request.status = ApprovalStatus.APPROVED
                request.decided_at = datetime.utcnow().isoformat()
                request.decided_by = approver_id
                self._stats["approved"] += 1
                await self._notify_decision(request, True)
                await self._persist(request)
                await self._cleanup(request.id)
                return True

        elif decision == ApprovalStatus.REJECTED:
            # Any rejection immediately rejects the request
            request.status = ApprovalStatus.REJECTED
            request.decided_at = datetime.utcnow().isoformat()
            request.decided_by = approver_id
            self._stats["rejected"] += 1
            await self._notify_decision(request, False)
            await self._persist(request)
            await self._cleanup(request.id)
            return True

        return True

    async def _notify_decision(self, request: ApprovalRequest, approved: bool):
        """Notify requester of decision."""
        pass  # Implement based on channel handlers

    async def _cleanup(self, request_id: str):
        """Clean up after decision."""
        if request_id in self._timeouts:
            self._timeouts[request_id].cancel()
            del self._timeouts[request_id]
        if request_id in self._pending:
            # Keep for audit, but could move to archive
            pass

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._pending.get(request_id)

    def get_pending_for_user(self, user_id: str, role: str) -> List[ApprovalRequest]:
        """Get pending approvals for a specific user/role."""
        pending = []
        for req in self._pending.values():
            if req.status == ApprovalStatus.PENDING:
                if not req.approver_roles or role in req.approver_roles:
                    # Check if user hasn't already voted
                    if not any(a.get("user_id") == user_id for a in req.approvals):
                        pending.append(req)
        return pending

    def get_stats(self) -> Dict[str, int]:
        return self._stats.copy()


# ─── Channel Handlers ────────────────────────────────────────────

async def whatsapp_approval_handler(request: ApprovalRequest, rule: ApprovalRule):
    """Send approval request via WhatsApp to approvers."""
    # This would integrate with the WhatsApp bridge
    # For now, log the request
    logger.info("WhatsApp approval request for %s: %s", request.id, request.payload)
    # TODO: Implement actual WhatsApp message sending


async def dashboard_approval_handler(request: ApprovalRequest, rule: ApprovalRule):
    """Dashboard notification (handled via WebSocket)."""
    # The dashboard polls for pending approvals via /api/approvals/pending
    logger.info("Dashboard approval request queued: %s", request.id)


async def email_approval_handler(request: ApprovalRequest, rule: ApprovalRule):
    """Send approval request via email."""
    # Integrate with email service
    logger.info("Email approval request for %s", request.id)
    # TODO: Implement email sending


# ─── Global Instance ──────────────────────────────────────────────

approval_engine = ApprovalEngine()

# Register default channel handlers
approval_engine.register_channel_handler(ApprovalChannel.DASHBOARD, dashboard_approval_handler)
approval_engine.register_channel_handler(ApprovalChannel.WHATSAPP, whatsapp_approval_handler)
approval_engine.register_channel_handler(ApprovalChannel.EMAIL, email_approval_handler)


# ─── Integration Helpers ──────────────────────────────────────────

async def request_approval(
    action_type: str,
    requester_id: str,
    client_id: int,
    payload: Dict[str, Any],
    amount: float = None,
    conversation_id: str = None,
) -> ApprovalRequest:
    """Quick helper to request approval."""
    return await approval_engine.request_approval(
        action_type=action_type,
        requester_id=requester_id,
        client_id=client_id,
        payload=payload,
        amount=amount,
        conversation_id=conversation_id,
    )


async def check_and_approve(
    action_type: str,
    requester_id: str,
    client_id: int,
    payload: Dict[str, Any],
    amount: float = None,
    conversation_id: str = None,
) -> Dict[str, Any]:
    """Check if approval needed, request if so, return result."""
    rule = approval_engine.check_requires_approval(action_type, amount)
    if not rule:
        return {"approved": True, "request_id": None}

    request = await approval_engine.request_approval(
        action_type=action_type,
        requester_id=requester_id,
        client_id=client_id,
        payload=payload,
        amount=amount,
        conversation_id=conversation_id,
    )

    if request.status == ApprovalStatus.APPROVED:
        return {"approved": True, "request_id": request.id}

    return {"approved": False, "request_id": request.id, "status": request.status.value}


def get_pending_approvals(user_id: str, role: str) -> List[ApprovalRequest]:
    """Get pending approvals for a user."""
    return approval_engine.get_pending_for_user(user_id, role)