"""
Figma Integration Service
Pulls design tokens (colors, typography, spacing) from Figma files
and syncs them to the platform's theme system.
"""
import json
import os
import sys
import httpx
from typing import Dict, List, Any, Optional

# Add agent-engine to path for settings
_AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agent-engine"))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from config import settings

FIGMA_API_BASE = "https://api.figma.com/v1"

# Design token node names we look for
TOKEN_NODE_NAMES = {
    "colors": ["colors", "color", "tokens/colors", "design-tokens/colors"],
    "typography": ["typography", "type", "tokens/typography", "design-tokens/typography"],
    "spacing": ["spacing", "space", "tokens/spacing", "design-tokens/spacing"],
}


class FigmaToken:
    """Represents a single design token extracted from Figma."""
    def __init__(self, name: str, value: Any, token_type: str = "color"):
        self.name = name
        self.value = value
        self.token_type = token_type

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "type": self.token_type}


class FigmaIntegration:
    """Figma API integration for design token sync."""

    def __init__(self):
        self.api_token = settings.figma_api_token
        self.file_key = settings.figma_file_key
        self._cache: Dict[str, List[FigmaToken]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_token and self.file_key)

    async def get_file(self) -> Optional[dict]:
        """Fetch the full Figma file document."""
        if not self.configured:
            return None
        headers = {"X-Figma-Token": self.api_token}
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{FIGMA_API_BASE}/files/{self.file_key}",
                    headers=headers,
                    timeout=30
                )
                if resp.status_code == 200:
                    return resp.json()
                return None
            except Exception:
                return None

    def _extract_tokens(self, node: dict, token_type: str = "color") -> List[FigmaToken]:
        """Recursively extract design tokens from Figma nodes."""
        tokens = []
        node_type = node.get("type", "")
        name = node.get("name", "").lower()

        if node_type == "RECTANGLE" and token_type == "color":
            fills = node.get("fills", [])
            if fills and fills[0].get("type") == "SOLID":
                color = fills[0].get("color", {})
                r = int(color.get("r", 0) * 255)
                g = int(color.get("g", 0) * 255)
                b = int(color.get("b", 0) * 255)
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
                tokens.append(FigmaToken(name.replace(" ", "-"), hex_color, "color"))

        # Recurse through children
        for child in node.get("children", []):
            tokens.extend(self._extract_tokens(child, token_type))

        return tokens

    async def sync_tokens(self) -> Dict[str, List[Dict]]:
        """Fetch and sync design tokens from Figma."""
        if not self.configured:
            return {"error": "FIGMA_API_TOKEN and FIGMA_FILE_KEY not configured in .env"}

        data = await self.get_file()
        if not data:
            return {"error": "Failed to fetch Figma file"}

        document = data.get("document", {})
        all_tokens: Dict[str, List[FigmaToken]] = {
            "colors": [],
            "typography": [],
            "spacing": [],
        }

        # Walk the document tree looking for token containers
        def walk(node: dict):
            name = node.get("name", "").lower()
            node_type = node.get("type", "")

            # Look for token containers by name
            for token_key, names in TOKEN_NODE_NAMES.items():
                if name in names:
                    tokens = self._extract_tokens(node, token_key)
                    all_tokens[token_key].extend(tokens)
                    return  # Don't recurse deeper into token containers

            # Also check for fill styles in components
            if node_type in ("COMPONENT", "FRAME", "INSTANCE") and node_type != "PAGE":
                fills = node.get("fills", [])
                if fills and fills[0].get("type") == "SOLID":
                    color = fills[0].get("color", {})
                    r = int(color.get("r", 0) * 255)
                    g = int(color.get("g", 0) * 255)
                    b = int(color.get("b", 0) * 255)
                    hex_color = f"#{r:02x}{g:02x}{b:02x}"
                    if name not in [t.name for t in all_tokens["colors"]]:
                        all_tokens["colors"].append(
                            FigmaToken(name.replace(" ", "-"), hex_color, "color")
                        )

            for child in node.get("children", []):
                walk(child)

        walk(document)

        # Cache and return
        result = {k: [t.to_dict() for t in v] for k, v in all_tokens.items()}
        self._cache = all_tokens
        return result

    async def apply_theme(self, tokens: Dict[str, List[Dict]]) -> dict:
        """Apply Figma tokens as a theme to the platform."""
        colors = tokens.get("colors", [])
        if not colors:
            return {"status": "no_colors", "message": "No color tokens found in Figma file"}

        # Find primary and secondary colors (first two colors or named ones)
        primary = None
        secondary = None
        for token in colors:
            name = token.get("name", "").lower()
            if "primary" in name:
                primary = token.get("value")
            elif "secondary" in name:
                secondary = token.get("value")

        # Fallback to first two colors
        if not primary and colors:
            primary = colors[0].get("value")
        if not secondary and len(colors) > 1:
            secondary = colors[1].get("value")

        if not primary or not secondary:
            return {"status": "insufficient", "message": "Need at least 2 colors"}

        return {
            "status": "applied",
            "primary_color": primary,
            "secondary_color": secondary,
            "token_count": len(colors),
        }

    def get_cached_tokens(self) -> Dict[str, List[Dict]]:
        """Get cached design tokens."""
        return {k: [t.to_dict() for t in v] for k, v in self._cache.items()}


# Singleton instance
figma_integration = FigmaIntegration()