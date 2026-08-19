"""
Phase 6: Compliance & Ops — GDPR/DPDP, Audit Logs, Status Page, White-label
"""
import json
import logging
import os
import hashlib
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger("compliance")


# ---------------------------------------------------------------------------
# 1. GDPR/DPDP Compliance
# ---------------------------------------------------------------------------

class ConsentType(Enum):
    MARKETING = "marketing"
    COMMUNICATION = "communication"
    DATA_PROCESSING = "data_processing"
    THIRD_PARTY_SHARING = "third_party_sharing"
    ANALYTICS = "analytics"


class ConsentStatus(Enum):
    GRANTED = "granted"
    DENIED = "denied"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


@dataclass
class ConsentRecord:
    """Record of user consent for data processing"""
    contact_id: str
    consent_type: ConsentType
    status: ConsentStatus
    granted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    expires_at: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    consent_method: str = "whatsapp"  # whatsapp, web, api, email

    def to_dict(self) -> Dict:
        return {
            "contact_id": self.contact_id,
            "consent_type": self.consent_type.value,
            "status": self.status.value,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "consent_method": self.consent_method,
        }


class ComplianceManager:
    """
    GDPR/DPDP compliance management.
    Handles consent, data export, right-to-delete, and data portability.
    """

    OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "बंद", "रद्द", "opt out", "end"}

    def __init__(self):
        self.consent_records: Dict[str, List[ConsentRecord]] = {}  # contact_id -> records
        self._deletion_requests: List[Dict] = []
        self._data_exports: List[Dict] = []
        self.opt_out_records: Dict[str, Dict] = {}

    # --- Consent Management ---

    def record_consent(self, contact_id: str, consent_type: ConsentType,
                       status: ConsentStatus = ConsentStatus.GRANTED,
                       method: str = "whatsapp",
                       ip: Optional[str] = None,
                       ua: Optional[str] = None) -> ConsentRecord:
        """Record a consent action"""
        record = ConsentRecord(
            contact_id=contact_id,
            consent_type=consent_type,
            status=status,
            ip_address=ip,
            user_agent=ua,
            consent_method=method,
        )
        if contact_id not in self.consent_records:
            self.consent_records[contact_id] = []
        self.consent_records[contact_id].append(record)
        logger.info(f"[+] Consent {status.value} for {contact_id} on {consent_type.value}")
        return record

    def check_consent(self, contact_id: str, consent_type: ConsentType) -> bool:
        """Check if a contact has granted a specific consent"""
        records = self.consent_records.get(contact_id, [])
        for r in reversed(records):  # Most recent first
            if r.consent_type == consent_type:
                if r.status == ConsentStatus.GRANTED:
                    # Check expiry
                    if r.expires_at:
                        expires = datetime.fromisoformat(r.expires_at)
                        if datetime.utcnow() > expires:
                            continue
                    return True
                elif r.status == ConsentStatus.WITHDRAWN:
                    return False
        return False

    def withdraw_consent(self, contact_id: str, consent_type: ConsentType) -> bool:
        """Withdraw a previously granted consent"""
        return bool(self.record_consent(
            contact_id, consent_type, ConsentStatus.WITHDRAWN
        ))

    def get_consent_history(self, contact_id: str) -> List[Dict]:
        """Get full consent history for a contact"""
        return [
            r.to_dict() for r in self.consent_records.get(contact_id, [])
        ]

    # --- Data Export (Right to Access) ---

    async def export_user_data(self, contact_id: str, client_id: int = 1) -> Optional[str]:
        """Export all data for a user (GDPR Article 15)"""
        from db import get_session, get_conversation_history, get_contact

        export = {
            "contact_id": contact_id,
            "exported_at": datetime.utcnow().isoformat(),
            "consent_records": self.get_consent_history(contact_id),
            "conversations": [],
            "profile": {},
        }

        async for session in get_session():
            # Get contact profile
            contact = await get_contact(session, contact_id, client_id)
            if contact:
                export["profile"] = {
                    "name": contact.name,
                    "phone": contact.phone_number,
                    "email": getattr(contact, 'email', ''),
                    "created_at": getattr(contact, 'created_at', ''),
                    "tags": getattr(contact, 'tags', []),
                }

            # Get conversation history
            messages = await get_conversation_history(session, contact_id, limit=1000)
            export["conversations"] = [
                {
                    "content": m.content,
                    "direction": m.direction,
                    "timestamp": m.created_at.isoformat() if hasattr(m.created_at, 'isoformat') else str(m.created_at),
                }
                for m in messages
            ]

        # Save export
        export_id = f"export_{contact_id}_{int(datetime.utcnow().timestamp())}"
        export_path = os.path.join(os.getcwd(), "exports", f"{export_id}.json")
        os.makedirs(os.path.dirname(export_path), exist_ok=True)

        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2, ensure_ascii=False, default=str)

        self._data_exports.append({
            "export_id": export_id,
            "contact_id": contact_id,
            "path": export_path,
            "created_at": datetime.utcnow().isoformat(),
        })

        logger.info(f"[v] Data exported for {contact_id}: {export_path}")
        return export_path

    # --- Right to Delete ---

    async def delete_user_data(self, contact_id: str, client_id: int = 1) -> bool:
        """Delete all data for a user (GDPR Article 17)"""
        from db import get_session
        from sqlalchemy import delete
        from db import Message, Contact, Appointment, Lead

        async for session in get_session():
            try:
                # Delete messages
                await session.execute(
                    delete(Message).where(Message.phone_number == contact_id)
                )
                # Delete contact
                await session.execute(
                    delete(Contact).where(Contact.phone_number == contact_id)
                )
                # Delete appointments
                await session.execute(
                    delete(Appointment).where(Appointment.phone_number == contact_id)
                )
                # Delete leads
                await session.execute(
                    delete(Lead).where(Lead.phone_number == contact_id)
                )
                await session.commit()

                # Remove consent records
                self.consent_records.pop(contact_id, None)

                # Log deletion
                self._deletion_requests.append({
                    "contact_id": contact_id,
                    "deleted_at": datetime.utcnow().isoformat(),
                    "reason": "user_request",
                })

                logger.info(f"[v] All data deleted for {contact_id}")
                return True
            except Exception as e:
                logger.error(f"Data deletion failed for {contact_id}: {e}")
                await session.rollback()
                return False

    def get_stats(self) -> Dict:
        """Get compliance statistics"""
        return {
            "total_consent_records": sum(len(v) for v in self.consent_records.values()),
            "unique_contacts_with_consent": len(self.consent_records),
            "total_deletion_requests": len(self._deletion_requests),
            "total_data_exports": len(self._data_exports),
        }

    def is_opt_out_message(self, message: str) -> bool:
        """Check if a message is an opt-out request in any supported language."""
        normalized = message.strip().lower()
        return normalized in self.OPT_OUT_KEYWORDS

    def check_opt_out(self, phone_number: str, client_id: int = 1) -> Dict:
        """Check if a phone number has opted out."""
        if phone_number in self.opt_out_records:
            record = self.opt_out_records[phone_number]
            if record.get("client_id") == client_id:
                return {"opted_out": True, "opted_out_at": record.get("opted_out_at"), "source": record.get("source")}
        return {"opted_out": False}

    def record_opt_out(self, phone_number: str, client_id: int = 1, source: str = "manual") -> Dict:
        """Record an opt-out for a phone number."""
        self.opt_out_records[phone_number] = {
            "client_id": client_id,
            "opted_out_at": datetime.utcnow().isoformat(),
            "source": source,
        }
        logger.info(f"[v] Opt-out recorded for {phone_number} (source={source})")
        return {"opted_out": True, "phone_number": phone_number}

    def check_can_send(self, phone_number: str, client_id: int = 1) -> bool:
        """Return False if the contact has opted out."""
        if phone_number in self.opt_out_records:
            record = self.opt_out_records[phone_number]
            if record.get("client_id") == client_id:
                return False
        return True


# ---------------------------------------------------------------------------
# 2. Enhanced Audit Logs
# ---------------------------------------------------------------------------

class AuditAction(Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    MESSAGE_SENT = "message.sent"
    MESSAGE_RECEIVED = "message.received"
    LEAD_CREATED = "lead.created"
    LEAD_UPDATED = "lead.updated"
    CAMPAIGN_CREATED = "campaign.created"
    CAMPAIGN_STARTED = "campaign.started"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"
    WEBHOOK_REGISTERED = "webhook.registered"
    WEBHOOK_UNREGISTERED = "webhook.unregistered"
    PLUGIN_INSTALLED = "plugin.installed"
    PLUGIN_UNINSTALLED = "plugin.uninstalled"
    SETTINGS_CHANGED = "settings.changed"
    USER_DELETED = "user.deleted"
    DATA_EXPORTED = "data.exported"
    ERROR = "error"


@dataclass
class AuditEntry:
    """A single audit log entry"""
    id: str
    action: AuditAction
    actor_id: str
    client_id: int
    resource_type: str = ""
    resource_id: str = ""
    details: Dict = field(default_factory=dict)
    ip_address: str = ""
    user_agent: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action": self.action.value,
            "actor_id": self.actor_id,
            "client_id": self.client_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "timestamp": self.timestamp,
        }


class AuditLogger:
    """
    Immutable audit log — every action is tracked.
    Logs are append-only and cannot be modified.
    """

    def __init__(self, max_entries: int = 10000):
        self._entries: List[AuditEntry] = []
        self._max_entries = max_entries

    def log(self, action: AuditAction, actor_id: str, client_id: int = 1,
            resource_type: str = "", resource_id: str = "",
            details: Optional[Dict] = None,
            ip: str = "", ua: str = "") -> AuditEntry:
        """Record an audit log entry"""
        entry = AuditEntry(
            id=f"audit_{int(datetime.utcnow().timestamp() * 1000)}_{secrets.token_hex(4)}",
            action=action,
            actor_id=actor_id,
            client_id=client_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip,
            user_agent=ua,
        )
        self._entries.append(entry)

        # Trim if over max
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        return entry

    def query(self, client_id: Optional[int] = None,
              action: Optional[AuditAction] = None,
              actor_id: Optional[str] = None,
              resource_type: Optional[str] = None,
              start_time: Optional[str] = None,
              end_time: Optional[str] = None,
              limit: int = 100) -> List[Dict]:
        """Query audit logs with filters"""
        results = self._entries

        if client_id:
            results = [e for e in results if e.client_id == client_id]
        if action:
            results = [e for e in results if e.action == action]
        if actor_id:
            results = [e for e in results if e.actor_id == actor_id]
        if resource_type:
            results = [e for e in results if e.resource_type == resource_type]
        if start_time:
            results = [e for e in results if e.timestamp >= start_time]
        if end_time:
            results = [e for e in results if e.timestamp <= end_time]

        return [e.to_dict() for e in results[-limit:]]

    def export(self, filepath: Optional[str] = None) -> str:
        """Export all audit logs to JSON"""
        if not filepath:
            filepath = os.path.join(
                os.getcwd(), "exports",
                f"audit_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            )
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in self._entries], f, indent=2, default=str)
        return filepath

    def get_stats(self) -> Dict:
        """Get audit log statistics"""
        return {
            "total_entries": len(self._entries),
            "unique_actions": len(set(e.action for e in self._entries)),
            "unique_actors": len(set(e.actor_id for e in self._entries)),
            "date_range": {
                "earliest": self._entries[0].timestamp if self._entries else None,
                "latest": self._entries[-1].timestamp if self._entries else None,
            },
        }


# ---------------------------------------------------------------------------
# 3. Status Page
# ---------------------------------------------------------------------------

class StatusPage:
    """
    Status page generator — shows system health, uptime, and incidents.
    """

    def __init__(self, app_name: str = "WhatsApp Agent Platform",
                 app_url: str = "https://status.yourapp.com"):
        self.app_name = app_name
        self.app_url = app_url
        self.incidents: List[Dict] = []
        self.maintenance_windows: List[Dict] = []
        self._start_time = datetime.utcnow()

    def record_incident(self, title: str, description: str,
                        severity: str = "minor",
                        components: Optional[List[str]] = None):
        """Record a system incident"""
        self.incidents.append({
            "id": f"inc_{int(datetime.utcnow().timestamp())}",
            "title": title,
            "description": description,
            "severity": severity,  # minor, major, critical
            "components": components or [],
            "status": "investigating",  # investigating, identified, monitoring, resolved
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "resolved_at": None,
        })

    def resolve_incident(self, incident_id: str):
        """Mark an incident as resolved"""
        for inc in self.incidents:
            if inc["id"] == incident_id:
                inc["status"] = "resolved"
                inc["resolved_at"] = datetime.utcnow().isoformat()
                inc["updated_at"] = datetime.utcnow().isoformat()
                break

    def schedule_maintenance(self, title: str, description: str,
                             start_time: str, end_time: str):
        """Schedule a maintenance window"""
        self.maintenance_windows.append({
            "id": f"maint_{int(datetime.utcnow().timestamp())}",
            "title": title,
            "description": description,
            "start_time": start_time,
            "end_time": end_time,
            "status": "scheduled",
            "created_at": datetime.utcnow().isoformat(),
        })

    def generate_html(self, component_status: Dict[str, str]) -> str:
        """Generate a status page HTML"""
        uptime_seconds = (datetime.utcnow() - self._start_time).total_seconds()
        uptime_days = uptime_seconds / 86400

        components_html = ""
        for name, status in component_status.items():
            color = {"up": "green", "down": "red", "degraded": "orange", "maintenance": "gray"}
            components_html += f"""
            <div style="display: flex; justify-content: space-between; padding: 12px; border-bottom: 1px solid #eee;">
                <span>{name}</span>
                <span style="color: {color.get(status, 'gray')}; font-weight: 600;">{status.upper()}</span>
            </div>"""

        incidents_html = ""
        for inc in self.incidents[-5:]:
            color = {"investigating": "red", "identified": "orange", "monitoring": "blue", "resolved": "green"}
            incidents_html += f"""
            <div style="padding: 12px; border-left: 4px solid {color.get(inc['status'], 'gray')}; margin: 8px 0; background: #f9f9f9;">
                <strong>{inc['title']}</strong>
                <span style="float: right; font-size: 12px; color: {color.get(inc['status'], 'gray')};">{inc['status']}</span>
                <p style="margin: 4px 0; font-size: 14px;">{inc['description']}</p>
                <small>{inc['created_at']}</small>
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{self.app_name} — Status</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 800px; margin: 0 auto; background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        h1 {{ margin: 0 0 8px; }}
        .uptime {{ font-size: 14px; color: #666; }}
        .all-clear {{ background: #d4edda; color: #155724; padding: 12px; border-radius: 8px; margin: 16px 0; text-align: center; font-weight: 600; }}
        .section {{ margin: 24px 0; }}
        .section h2 {{ font-size: 18px; border-bottom: 2px solid #eee; padding-bottom: 8px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{self.app_name}</h1>
        <div class="uptime">Uptime: {uptime_days:.1f} days</div>
        
        <div class="all-clear">✅ All Systems Operational</div>
        
        <div class="section">
            <h2>Components</h2>
            {components_html}
        </div>
        
        <div class="section">
            <h2>Recent Incidents</h2>
            {incidents_html if incidents_html else '<p style="color: #666;">No recent incidents</p>'}
        </div>
        
        <div class="section">
            <h2>Scheduled Maintenance</h2>
            {self._maintenance_html()}
        </div>
        
        <div style="text-align: center; margin-top: 24px; font-size: 12px; color: #999;">
            Last updated: {datetime.utcnow().isoformat()}
        </div>
    </div>
</body>
</html>"""

    def _maintenance_html(self) -> str:
        if not self.maintenance_windows:
            return '<p style="color: #666;">No scheduled maintenance</p>'
        html = ""
        for m in self.maintenance_windows:
            html += f"""
            <div style="padding: 12px; border-left: 4px solid #ffc107; margin: 8px 0; background: #fff8e1;">
                <strong>{m['title']}</strong>
                <p style="margin: 4px 0; font-size: 14px;">{m['description']}</p>
                <small>{m['start_time']} — {m['end_time']}</small>
            </div>"""
        return html


# ---------------------------------------------------------------------------
# 4. White-label Mode
# ---------------------------------------------------------------------------

@dataclass
class WhiteLabelConfig:
    """White-label configuration for resellers"""
    client_id: int
    brand_name: str = "WhatsApp Agent"
    brand_logo_url: str = ""
    primary_color: str = "#25D366"
    secondary_color: str = "#128C7E"
    custom_domain: str = ""
    favicon_url: str = ""
    footer_text: str = "Powered by WhatsApp Agent Platform"
    hide_branding: bool = False
    custom_css: str = ""
    support_email: str = ""
    support_phone: str = ""
    terms_url: str = ""
    privacy_url: str = ""
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "client_id": self.client_id,
            "brand_name": self.brand_name,
            "brand_logo_url": self.brand_logo_url,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "custom_domain": self.custom_domain,
            "favicon_url": self.favicon_url,
            "footer_text": self.footer_text,
            "hide_branding": self.hide_branding,
            "custom_css": self.custom_css,
            "support_email": self.support_email,
            "support_phone": self.support_phone,
            "terms_url": self.terms_url,
            "privacy_url": self.privacy_url,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }


class WhiteLabelManager:
    """Manage white-label configurations for resellers"""

    def __init__(self):
        self.configs: Dict[int, WhiteLabelConfig] = {}  # client_id -> config

    def set_config(self, client_id: int, config: WhiteLabelConfig) -> WhiteLabelConfig:
        """Set white-label config for a client"""
        self.configs[client_id] = config
        logger.info(f"[+] White-label config set for client {client_id}: {config.brand_name}")
        return config

    def get_config(self, client_id: int) -> Optional[WhiteLabelConfig]:
        """Get white-label config for a client"""
        return self.configs.get(client_id)

    def get_branding(self, client_id: int) -> Dict:
        """Get branding assets for a client"""
        config = self.get_config(client_id)
        if not config or not config.is_active:
            return {
                "brand_name": "WhatsApp Agent",
                "primary_color": "#25D366",
                "hide_branding": False,
            }
        return {
            "brand_name": config.brand_name,
            "brand_logo_url": config.brand_logo_url,
            "primary_color": config.primary_color,
            "secondary_color": config.secondary_color,
            "favicon_url": config.favicon_url,
            "footer_text": config.footer_text,
            "hide_branding": config.hide_branding,
            "custom_css": config.custom_css,
            "support_email": config.support_email,
            "support_phone": config.support_phone,
            "terms_url": config.terms_url,
            "privacy_url": config.privacy_url,
        }

    def generate_widget_embed(self, client_id: int, widget_id: str) -> Optional[str]:
        """Generate white-labeled widget embed code"""
        branding = self.get_branding(client_id)
        from services.web_chat_widget import widget_manager
        widget = widget_manager.get_widget(widget_id)
        if not widget:
            return None

        # Override widget colors with white-label branding
        widget.primary_color = branding.get("primary_color", widget.primary_color)
        widget.title = branding.get("brand_name", widget.title)

        if branding.get("hide_branding"):
            # Remove "Powered by" text
            pass

        return widget.generate_embed_code()


# Global instances
compliance_manager = ComplianceManager()
audit_logger = AuditLogger()
status_page = StatusPage()
white_label_manager = WhiteLabelManager()