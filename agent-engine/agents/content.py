"""
Content Agent — generates and manages message templates, FAQ content, and knowledge base articles.
"""
from agents.base import BaseAgent
import logging

logger = logging.getLogger("content_agent")


class ContentAgent(BaseAgent):
    def __init__(self):
        system_prompt = (
            "You are the Content Manager. Your goal is to create and manage business content. "
            "\n\nRULES:\n"
            "1. Use 'create_template' for reusable message templates.\n"
            "2. Use 'render_template' to populate templates with variables.\n"
            "3. Use 'create_knowledge_article' for FAQ/knowledge base entries.\n"
            "4. Use 'update_template' to refine based on performance data.\n"
            "5. Content should match the owner's brand voice (formal/casual/playful).\n"
            "6. Always include a clear call-to-action in templates."
        )
        tools = [
            "create_template",
            "render_template",
            "update_template",
            "create_knowledge_article",
            "list_templates",
        ]
        super().__init__(
            name="ContentWriter",
            role="Content & Templates",
            system_prompt=system_prompt,
            tools=tools,
        )
