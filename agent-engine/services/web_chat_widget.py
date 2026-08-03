"""
Embeddable Web Chat Widget — deployable script for client websites
"""
import json
import hashlib
import logging
import secrets
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger("web_chat_widget")


class WidgetConfig:
    """Configuration for a web chat widget instance"""

    def __init__(self, client_id: int, domain: str, 
                 primary_color: str = "#25D366",
                 title: str = "Chat with us",
                 subtitle: str = "We typically reply in minutes",
                 position: str = "right",
                 greeting_message: str = "Hi! How can I help you today?",
                 agent_endpoint: str = "http://localhost:8000/api/message",
                 allowed_domains: Optional[List[str]] = None):
        self.widget_id = hashlib.md5(f"{client_id}_{domain}".encode()).hexdigest()[:12]
        self.client_id = client_id
        self.domain = domain
        self.primary_color = primary_color
        self.title = title
        self.subtitle = subtitle
        self.position = position  # 'left' or 'right'
        self.greeting_message = greeting_message
        self.agent_endpoint = agent_endpoint
        self.api_key = secrets.token_hex(16)
        self.is_active = True
        self.allowed_domains = allowed_domains or [domain]
        self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict:
        return {
            "widget_id": self.widget_id,
            "client_id": self.client_id,
            "domain": self.domain,
            "primary_color": self.primary_color,
            "title": self.title,
            "subtitle": self.subtitle,
            "position": self.position,
            "greeting_message": self.greeting_message,
            "agent_endpoint": self.agent_endpoint,
            "api_key": self.api_key,
            "is_active": self.is_active,
            "allowed_domains": self.allowed_domains,
            "created_at": self.created_at,
        }

    def generate_embed_code(self) -> str:
        """Generate the embed script HTML"""
        return f'''<!-- WhatsApp Agent Chat Widget -->
<script>
(function() {{
    var widgetId = "{self.widget_id}";
    var apiKey = "{self.api_key}";
    var agentUrl = "{self.agent_endpoint}";
    
    var container = document.createElement('div');
    container.id = 'wa-agent-chat-' + widgetId;
    container.innerHTML = `
        <div id="wa-chat-toggle" style="
            position: fixed;
            bottom: 20px;
            {self.position}: 20px;
            z-index: 999999;
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: {self.primary_color};
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.2s;
        ">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="white">
                <path d="M12 2C6.48 2 2 6.48 2 12c0 2.17.68 4.17 1.85 5.81L2 22l4.32-1.85C7.83 21.32 9.83 22 12 22c5.52 0 10-4.48 10-10S17.52 2 12 2z"/>
            </svg>
        </div>
        <div id="wa-chat-box" style="
            display: none;
            position: fixed;
            bottom: 90px;
            {self.position}: 20px;
            z-index: 999999;
            width: 350px;
            height: 500px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        ">
            <div style="background: {self.primary_color}; padding: 16px; color: white;">
                <div style="font-weight: 600; font-size: 16px;">{self.title}</div>
                <div style="font-size: 12px; opacity: 0.9;">{self.subtitle}</div>
            </div>
            <div id="wa-messages" style="height: 360px; overflow-y: auto; padding: 12px; background: #f5f5f5;"></div>
            <div style="display: flex; border-top: 1px solid #e0e0e0;">
                <input id="wa-input" type="text" placeholder="Type a message..." 
                    style="flex: 1; border: none; padding: 12px; outline: none;">
                <button id="wa-send" style="
                    background: {self.primary_color}; 
                    color: white; 
                    border: none; 
                    padding: 12px 16px; 
                    cursor: pointer;
                ">Send</button>
            </div>
        </div>
    `;
    document.body.appendChild(container);
    
    var toggle = document.getElementById('wa-chat-toggle');
    var chatBox = document.getElementById('wa-chat-box');
    var messages = document.getElementById('wa-messages');
    var input = document.getElementById('wa-input');
    var sendBtn = document.getElementById('wa-send');
    
    toggle.onclick = function() {{
        chatBox.style.display = chatBox.style.display === 'none' ? 'block' : 'none';
        if (chatBox.style.display === 'block' && messages.children.length === 0) {{
            addMessage('{self.greeting_message}', 'bot');
        }}
    }};
    
    function addMessage(text, sender) {{
        var msg = document.createElement('div');
        msg.style.cssText = 'margin: 8px 0; padding: 8px 12px; border-radius: 12px; max-width: 80%; ' +
            (sender === 'bot' ? 'background: white; self-align: flex-start;' : 'background: {self.primary_color}; color: white; margin-left: auto;');
        msg.textContent = text;
        messages.appendChild(msg);
        messages.scrollTop = messages.scrollHeight;
    }}
    
    async function sendMessage() {{
        var text = input.value.trim();
        if (!text) return;
        addMessage(text, 'user');
        input.value = '';
        
        try {{
            var resp = await fetch(agentUrl, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json', 'X-API-Key': apiKey }},
                body: JSON.stringify({{ phone_number: 'web_' + widgetId + '_' + Date.now(), message: text }})
            }});
            var data = await resp.json();
            addMessage(data.reply || 'Sorry, I couldn\\'t process that.', 'bot');
        }} catch(e) {{
            addMessage('Connection error. Please try again.', 'bot');
        }}
    }}
    
    sendBtn.onclick = sendMessage;
    input.onkeypress = function(e) {{ if (e.key === 'Enter') sendMessage(); }};
}})();
</script>'''

    @classmethod
    def from_dict(cls, data: Dict) -> "WidgetConfig":
        config = cls(
            client_id=data["client_id"],
            domain=data["domain"],
            primary_color=data.get("primary_color", "#25D366"),
            title=data.get("title", "Chat with us"),
            subtitle=data.get("subtitle", "We typically reply in minutes"),
            position=data.get("position", "right"),
            greeting_message=data.get("greeting_message", "Hi! How can I help you today?"),
            agent_endpoint=data.get("agent_endpoint", "http://localhost:8000/api/message"),
            allowed_domains=data.get("allowed_domains"),
        )
        config.widget_id = data.get("widget_id", config.widget_id)
        config.api_key = data.get("api_key", config.api_key)
        config.is_active = data.get("is_active", True)
        config.created_at = data.get("created_at", config.created_at)
        return config


class WidgetManager:
    """Manages multiple widget configurations"""

    def __init__(self):
        self.widgets: Dict[str, WidgetConfig] = {}

    def create_widget(self, config: WidgetConfig) -> WidgetConfig:
        """Register a new widget"""
        self.widgets[config.widget_id] = config
        logger.info(f"[+] Widget created: {config.widget_id} for {config.domain}")
        return config

    def get_widget(self, widget_id: str) -> Optional[WidgetConfig]:
        """Get widget by ID"""
        return self.widgets.get(widget_id)

    def get_widget_by_domain(self, domain: str) -> Optional[WidgetConfig]:
        """Find widget by domain"""
        for widget in self.widgets.values():
            if domain in widget.allowed_domains:
                return widget
        return None

    def validate_request(self, widget_id: str, api_key: str, origin: str) -> bool:
        """Validate a widget API request"""
        widget = self.get_widget(widget_id)
        if not widget or not widget.is_active:
            return False
        if widget.api_key != api_key:
            return False
        # Check origin domain
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        request_domain = parsed.hostname or origin
        if not any(request_domain.endswith(d) for d in widget.allowed_domains):
            return False
        return True

    def deactivate(self, widget_id: str):
        """Deactivate a widget"""
        widget = self.get_widget(widget_id)
        if widget:
            widget.is_active = False

    def list_widgets(self, client_id: Optional[int] = None) -> List[WidgetConfig]:
        """List all widgets, optionally filtered by client"""
        if client_id:
            return [w for w in self.widgets.values() if w.client_id == client_id]
        return list(self.widgets.values())


# Global widget manager
widget_manager = WidgetManager()