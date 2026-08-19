"""
Message Template Management — CRUD for WhatsApp message templates
Stores templates for bulk campaigns with variables, categories, and approval status.
"""
import os
import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("templates")


class TemplateStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class TemplateCategory(str, Enum):
    PROMOTIONAL = "promotional"
    TRANSACTIONAL = "transactional"
    REMINDER = "reminder"
    WELCOME = "welcome"
    FOLLOW_UP = "follow_up"
    SUPPORT = "support"
    CUSTOM = "custom"


@dataclass
class MessageTemplate:
    """A WhatsApp message template with variables"""
    id: str
    client_id: int
    name: str
    category: TemplateCategory
    content: str
    variables: List[str] = field(default_factory=list)
    language: str = "en"
    status: TemplateStatus = TemplateStatus.DRAFT
    meta_template_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "name": self.name,
            "category": self.category.value if isinstance(self.category, TemplateCategory) else self.category,
            "content": self.content,
            "variables": self.variables,
            "language": self.language,
            "status": self.status.value if isinstance(self.status, TemplateStatus) else self.status,
            "meta_template_id": self.meta_template_id,
            "rejection_reason": self.rejection_reason,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TemplateManager:
    """Manage message templates for a client"""

    def __init__(self):
        self.templates: Dict[str, MessageTemplate] = {}
        self._load_templates()

    def _load_templates(self):
        """Load templates from disk if available"""
        try:
            template_dir = os.path.join(os.path.dirname(__file__), "..", "agent-engine", "data", "templates")
            os.makedirs(template_dir, exist_ok=True)
            template_file = os.path.join(template_dir, "templates.json")
            if os.path.exists(template_file):
                with open(template_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for t in data.get("templates", []):
                        template = MessageTemplate(
                            id=t["id"],
                            client_id=t["client_id"],
                            name=t["name"],
                            category=TemplateCategory(t["category"]),
                            content=t["content"],
                            variables=t.get("variables", []),
                            language=t.get("language", "en"),
                            status=TemplateStatus(t.get("status", "draft")),
                            meta_template_id=t.get("meta_template_id"),
                            rejection_reason=t.get("rejection_reason"),
                            tags=t.get("tags", []),
                            created_at=t.get("created_at", datetime.utcnow().isoformat()),
                            updated_at=t.get("updated_at", datetime.utcnow().isoformat()),
                        )
                        self.templates[template.id] = template
        except Exception as e:
            logger.warning(f"Failed to load templates: {e}")

    def _save_templates(self):
        """Save templates to disk"""
        try:
            template_dir = os.path.join(os.path.dirname(__file__), "..", "agent-engine", "data", "templates")
            os.makedirs(template_dir, exist_ok=True)
            template_file = os.path.join(template_dir, "templates.json")
            data = {
                "templates": [t.to_dict() for t in self.templates.values()]
            }
            with open(template_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Failed to save templates: {e}")

    def create_template(self, client_id: int, name: str, category: str, content: str,
                        language: str = "en", tags: List[str] = None) -> MessageTemplate:
        """Create a new message template"""
        import hashlib
        template_id = hashlib.md5(f"{client_id}_{name}_{datetime.utcnow().timestamp()}".encode()).hexdigest()[:12]

        cat = TemplateCategory(category) if category in [c.value for c in TemplateCategory] else TemplateCategory.CUSTOM
        variables = self._extract_variables(content)

        template = MessageTemplate(
            id=template_id,
            client_id=client_id,
            name=name,
            category=cat,
            content=content,
            variables=variables,
            language=language,
            tags=tags or [],
        )
        self.templates[template_id] = template
        self._save_templates()
        return template

    def _extract_variables(self, content: str) -> List[str]:
        """Extract template variables like {{name}}, {{date}}"""
        import re
        return list(set(re.findall(r'\{\{(\w+)\}\}', content)))

    def get_template(self, template_id: str) -> Optional[MessageTemplate]:
        return self.templates.get(template_id)

    def get_templates_by_client(self, client_id: int) -> List[MessageTemplate]:
        return [t for t in self.templates.values() if t.client_id == client_id]

    def get_templates_by_status(self, client_id: int, status: str) -> List[MessageTemplate]:
        return [t for t in self.templates.values() if t.client_id == client_id and t.status == status]

    def update_template(self, template_id: str, **kwargs) -> Optional[MessageTemplate]:
        template = self.templates.get(template_id)
        if not template:
            return None
        for key, value in kwargs.items():
            if hasattr(template, key):
                setattr(template, key, value)
        template.updated_at = datetime.utcnow().isoformat()
        if "content" in kwargs:
            template.variables = self._extract_variables(kwargs["content"])
        self._save_templates()
        return template

    def delete_template(self, template_id: str) -> bool:
        if template_id in self.templates:
            del self.templates[template_id]
            self._save_templates()
            return True
        return False

    def render_template(self, template_id: str, variables: Dict[str, str]) -> str:
        """Render template with provided variables"""
        template = self.templates.get(template_id)
        if not template:
            return ""
        content = template.content
        for key, value in variables.items():
            content = content.replace("{{" + key + "}}", str(value))
        return content

    def get_stats(self, client_id: int) -> Dict[str, Any]:
        """Get template statistics for a client"""
        templates = self.get_templates_by_client(client_id)
        return {
            "total": len(templates),
            "by_status": {s: sum(1 for t in templates if t.status == s) for s in TemplateStatus},
            "by_category": {c.value: sum(1 for t in templates if t.category == c) for c in TemplateCategory},
        }


template_manager = TemplateManager()
