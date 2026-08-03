"""
Plugin/Skill Marketplace — let developers build and share vertical packs
"""
import json
import logging
import secrets
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger("plugin_marketplace")


class PluginType(Enum):
    VERTICAL_PACK = "vertical_pack"      # Doctor, CA, Lawyer, Restaurant
    CHANNEL_ADAPTER = "channel_adapter"  # Instagram, Telegram, etc.
    AI_TOOL = "ai_tool"                  # Custom AI function
    UI_THEME = "ui_theme"                # Dashboard theme
    INTEGRATION = "integration"          # External API integration
    WORKFLOW = "workflow"                # Custom workflow template


class PluginStatus(Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


@dataclass
class PluginManifest:
    """Plugin metadata — similar to npm package.json"""
    id: str
    name: str
    version: str
    type: PluginType
    author_id: str
    author_name: str
    description: str
    icon_url: str = ""
    tags: List[str] = field(default_factory=list)
    min_platform_version: str = "1.0.0"
    dependencies: Dict[str, str] = field(default_factory=dict)
    permissions: List[str] = field(default_factory=list)
    config_schema: Dict = field(default_factory=dict)
    entry_point: str = "main.py"
    status: PluginStatus = PluginStatus.DRAFT
    install_count: int = 0
    rating: float = 0.0
    price: float = 0.0  # 0 = free
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "type": self.type.value,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "description": self.description,
            "icon_url": self.icon_url,
            "tags": self.tags,
            "min_platform_version": self.min_platform_version,
            "dependencies": self.dependencies,
            "permissions": self.permissions,
            "config_schema": self.config_schema,
            "entry_point": self.entry_point,
            "status": self.status.value,
            "install_count": self.install_count,
            "rating": self.rating,
            "price": self.price,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PluginInstallation:
    """Tracks a plugin installation for a client"""

    def __init__(self, plugin_id: str, client_id: int, config: Optional[Dict] = None):
        self.plugin_id = plugin_id
        self.client_id = client_id
        self.config = config or {}
        self.is_active = True
        self.installed_at = datetime.utcnow().isoformat()
        self.last_used_at: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "plugin_id": self.plugin_id,
            "client_id": self.client_id,
            "config": self.config,
            "is_active": self.is_active,
            "installed_at": self.installed_at,
            "last_used_at": self.last_used_at,
        }


class PluginMarketplace:
    """
    Plugin marketplace for the platform.
    Developers can submit plugins, clients can install them.
    """

    def __init__(self):
        self.plugins: Dict[str, PluginManifest] = {}
        self.installations: Dict[str, PluginInstallation] = {}  # key: f"{plugin_id}_{client_id}"
        self._reviews: List[Dict] = []

    def submit(self, manifest: PluginManifest) -> PluginManifest:
        """Submit a new plugin"""
        self.plugins[manifest.id] = manifest
        logger.info(f"[+] Plugin submitted: {manifest.name} v{manifest.version} by {manifest.author_name}")
        return manifest

    def approve(self, plugin_id: str) -> bool:
        """Approve a plugin for publishing"""
        plugin = self.plugins.get(plugin_id)
        if plugin and plugin.status == PluginStatus.PENDING_REVIEW:
            plugin.status = PluginStatus.APPROVED
            return True
        return False

    def publish(self, plugin_id: str) -> bool:
        """Publish an approved plugin"""
        plugin = self.plugins.get(plugin_id)
        if plugin and plugin.status == PluginStatus.APPROVED:
            plugin.status = PluginStatus.PUBLISHED
            return True
        return False

    def install(self, plugin_id: str, client_id: int,
                config: Optional[Dict] = None) -> Optional[PluginInstallation]:
        """Install a plugin for a client"""
        plugin = self.plugins.get(plugin_id)
        if not plugin or plugin.status not in [PluginStatus.PUBLISHED, PluginStatus.APPROVED]:
            logger.warning(f"Cannot install plugin {plugin_id}: not published")
            return None

        key = f"{plugin_id}_{client_id}"
        if key in self.installations:
            logger.info(f"Plugin {plugin_id} already installed for client {client_id}")
            return self.installations[key]

        installation = PluginInstallation(plugin_id, client_id, config)
        self.installations[key] = installation
        plugin.install_count += 1
        logger.info(f"[v] Plugin {plugin.name} installed for client {client_id}")
        return installation

    def uninstall(self, plugin_id: str, client_id: int) -> bool:
        """Uninstall a plugin"""
        key = f"{plugin_id}_{client_id}"
        if key in self.installations:
            self.installations[key].is_active = False
            return True
        return False

    def get_installed(self, client_id: int) -> List[Dict]:
        """Get all installed plugins for a client"""
        return [
            {
                "plugin": self.plugins.get(inst.plugin_id).to_dict() if self.plugins.get(inst.plugin_id) else {},
                "installation": inst.to_dict(),
            }
            for inst in self.installations.values()
            if inst.client_id == client_id and inst.is_active
        ]

    def search(self, query: str, plugin_type: Optional[PluginType] = None) -> List[Dict]:
        """Search available plugins"""
        results = []
        for plugin in self.plugins.values():
            if plugin.status != PluginStatus.PUBLISHED:
                continue
            if plugin_type and plugin.type != plugin_type:
                continue
            if query.lower() in plugin.name.lower() or query.lower() in plugin.description.lower():
                results.append(plugin.to_dict())
        return results

    def add_review(self, plugin_id: str, client_id: int, rating: int,
                   comment: str = "") -> Dict:
        """Add a review for a plugin"""
        review = {
            "plugin_id": plugin_id,
            "client_id": client_id,
            "rating": max(1, min(5, rating)),
            "comment": comment,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._reviews.append(review)

        # Recalculate average rating
        plugin_reviews = [r for r in self._reviews if r["plugin_id"] == plugin_id]
        if plugin_reviews:
            plugin = self.plugins.get(plugin_id)
            if plugin:
                plugin.rating = round(
                    sum(r["rating"] for r in plugin_reviews) / len(plugin_reviews), 1
                )

        return review

    def get_stats(self) -> Dict:
        """Get marketplace statistics"""
        return {
            "total_plugins": len(self.plugins),
            "published": sum(1 for p in self.plugins.values() if p.status == PluginStatus.PUBLISHED),
            "pending_review": sum(1 for p in self.plugins.values() if p.status == PluginStatus.PENDING_REVIEW),
            "total_installs": sum(p.install_count for p in self.plugins.values()),
            "total_developers": len(set(p.author_id for p in self.plugins.values())),
        }


# Global marketplace instance
marketplace = PluginMarketplace()