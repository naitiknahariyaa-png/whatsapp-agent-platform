"""
Generic Professional Services Bot Framework
Base class that all vertical packs (Doctor, Lawyer, CA, Restaurant, Salon) extend.
"""
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
import re
from datetime import datetime


class ProfessionalServiceBot(ABC):
    """
    Base class for all professional service vertical packs.
    Each vertical (doctor, lawyer, ca, restaurant) extends this class
    and provides vertical-specific configuration.
    """

    def __init__(self, vertical_name: str, config: Dict[str, Any]):
        self.vertical_name = vertical_name
        self.config = config
        self.name = config.get("name", vertical_name.title())
        self.description = config.get("description", "")
        self.specialization = config.get("specialization", "")
        self.document_types = config.get("document_types", [])
        self.disclaimer = config.get("disclaimer", "")
        self.booking_flow = config.get("booking_flow", {})
        self.reminders = config.get("reminders", {})
        self.faq_source = config.get("faq_source", "")

    @abstractmethod
    def get_intents(self) -> List[str]:
        """Return list of intents this vertical handles"""
        pass

    @abstractmethod
    def get_response(self, intent: str, message: str, entities: Dict) -> str:
        """Generate response for a given intent"""
        pass

    @abstractmethod
    def get_booking_questions(self) -> List[str]:
        """Return the questions to ask for appointment booking"""
        pass

    def get_document_checklist(self) -> List[str]:
        """Return document checklist for this vertical"""
        return self.document_types

    def get_reminders(self) -> Dict:
        """Return reminder schedule"""
        return self.reminders

    def get_disclaimer(self) -> str:
        """Return legal disclaimer for this vertical"""
        return self.disclaimer

    def should_show_disclaimer(self) -> bool:
        """Whether to show disclaimer for this vertical"""
        return bool(self.disclaimer)

    def extract_entities(self, message: str) -> Dict:
        """Extract date, time, name from message"""
        entities = {}
        msg = message.lower()

        # Extract date
        for pattern in [r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", r"(kal|aaj|parson|today|tomorrow)"]:
            m = re.search(pattern, msg)
            if m:
                entities["date"] = m.group(0)
                break

        # Extract time
        for pattern in [r"(\d{1,2}):(\d{2})\s*(am|pm)?", r"(\d{1,2})\s*(am|pm|baje|o'clock)"]:
            m = re.search(pattern, msg)
            if m:
                entities["time"] = m.group(0)
                break

        # Extract person name (after "name" or "mere naam")
        for pattern in [r"mera naam (\w+)", r"my name is (\w+)", r"name (\w+) hai"]:
            m = re.search(pattern, msg)
            if m:
                entities["person_name"] = m.group(1)
                break

        # Extract location (after "se" or "from")
        for pattern in [r"(\w+) se", r"from (\w+)"]:
            m = re.search(pattern, msg)
            if m:
                entities["location"] = m.group(1)
                break

        return entities

    def to_dict(self) -> Dict:
        """Serialize to dict for API responses"""
        return {
            "vertical": self.vertical_name,
            "name": self.name,
            "description": self.description,
            "specialization": self.specialization,
            "document_types": self.document_types,
            "disclaimer": self.disclaimer,
            "intents": self.get_intents(),
        }


# Registry for all vertical packs
VERTICAL_REGISTRY: Dict[str, ProfessionalServiceBot] = {}


def register_vertical(name: str, bot_class: type, config: Dict):
    """Register a vertical pack in the global registry"""
    VERTICAL_REGISTRY[name] = bot_class(name, config)


def get_vertical(name: str) -> Optional[ProfessionalServiceBot]:
    """Get a vertical bot instance by name"""
    return VERTICAL_REGISTRY.get(name)


def list_verticals() -> List[str]:
    """List all registered verticals"""
    return list(VERTICAL_REGISTRY.keys())
</arg_value>
</write_to_file></tool_call>