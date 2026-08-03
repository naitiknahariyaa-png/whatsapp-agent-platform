"""
Referral/Affiliate System — track referrals, commissions, and rewards
"""
import json
import logging
import secrets
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field

logger = logging.getLogger("referral_system")


class ReferralStatus(Enum):
    PENDING = "pending"        # Referral clicked but not converted
    CONVERTED = "converted"    # Referred contact became a lead/customer
    REWARDED = "rewarded"      # Referrer received their reward
    EXPIRED = "expired"        # Referral link expired
    CANCELLED = "cancelled"    # Referral was cancelled


class RewardType(Enum):
    DISCOUNT = "discount"              # % off next purchase
    FREE_MONTH = "free_month"         # 1 month free subscription
    CASHBACK = "cashback"             # Fixed amount cashback
    POINTS = "points"                 # Loyalty points
    CREDIT = "credit"                 # Account credit
    CUSTOM = "custom"                 # Custom reward


@dataclass
class ReferralProgram:
    """A referral/affiliate program definition"""
    id: str
    name: str
    description: str = ""
    reward_type: RewardType = RewardType.DISCOUNT
    reward_value: float = 10.0  # Amount or percentage
    reward_description: str = "10% discount"
    referrer_gets: str = "Reward for referrer"
    referee_gets: str = "Welcome bonus for new contact"
    max_referrals_per_user: int = 100
    expiry_days: int = 30
    is_active: bool = True
    client_id: int = 1
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "reward_type": self.reward_type.value,
            "reward_value": self.reward_value,
            "reward_description": self.reward_description,
            "referrer_gets": self.referrer_gets,
            "referee_gets": self.referee_gets,
            "max_referrals_per_user": self.max_referrals_per_user,
            "expiry_days": self.expiry_days,
            "is_active": self.is_active,
            "client_id": self.client_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ReferralProgram":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            reward_type=RewardType(data["reward_type"]),
            reward_value=data.get("reward_value", 10.0),
            reward_description=data.get("reward_description", ""),
            referrer_gets=data.get("referrer_gets", ""),
            referee_gets=data.get("referee_gets", ""),
            max_referrals_per_user=data.get("max_referrals_per_user", 100),
            expiry_days=data.get("expiry_days", 30),
            is_active=data.get("is_active", True),
            client_id=data.get("client_id", 1),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


class ReferralLink:
    """A unique referral link for a contact"""

    def __init__(self, program_id: str, referrer_contact_id: str, 
                 client_id: int = 1, custom_code: str = ""):
        self.code = custom_code or secrets.token_hex(8)
        self.program_id = program_id
        self.referrer_contact_id = referrer_contact_id
        self.client_id = client_id
        self.referred_contacts: List[str] = []
        self.status = ReferralStatus.PENDING
        self.created_at = datetime.utcnow().isoformat()
        self.expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()
        self.conversion_count = 0
        self.reward_claimed = False

    @property
    def referral_url(self) -> str:
        return f"https://ref.yourapp.com/r/{self.code}"

    def to_dict(self) -> Dict:
        return {
            "code": self.code,
            "program_id": self.program_id,
            "referrer_contact_id": self.referrer_contact_id,
            "client_id": self.client_id,
            "referral_url": self.referral_url,
            "referred_contacts": self.referred_contacts,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "conversion_count": self.conversion_count,
            "reward_claimed": self.reward_claimed,
        }


class ReferralSystem:
    """
    Complete referral/affiliate system with:
    - Program management
    - Unique referral link generation
    - Conversion tracking
    - Reward processing
    - Performance analytics
    """

    def __init__(self):
        self.programs: Dict[str, ReferralProgram] = {}
        self.links: Dict[str, ReferralLink] = {}  # key: code
        self._rewards_pending: List[Dict] = []

    def create_program(self, program: ReferralProgram) -> ReferralProgram:
        """Create a new referral program"""
        self.programs[program.id] = program
        logger.info(f"[+] Referral program created: {program.name} ({program.id})")
        return program

    def get_program(self, program_id: str) -> Optional[ReferralProgram]:
        """Get a program by ID"""
        return self.programs.get(program_id)

    def create_link(self, program_id: str, referrer_contact_id: str,
                    client_id: int = 1) -> Optional[str]:
        """Create a referral link for a contact"""
        program = self.get_program(program_id)
        if not program or not program.is_active:
            logger.warning(f"Cannot create link: program {program_id} not found/inactive")
            return None

        # Check if referrer already has a link for this program
        for link in self.links.values():
            if (link.program_id == program_id and 
                link.referrer_contact_id == referrer_contact_id and
                link.status == ReferralStatus.PENDING):
                return link.code

        link = ReferralLink(program_id, referrer_contact_id, client_id)
        self.links[link.code] = link
        logger.info(f"[+] Referral link created: {link.code}")
        return link.code

    def get_link(self, code: str) -> Optional[ReferralLink]:
        """Get a referral link by code"""
        return self.links.get(code)

    def process_referral(self, code: str, referred_contact_id: str) -> bool:
        """Process when someone clicks a referral link"""
        link = self.get_link(code)
        if not link:
            logger.warning(f"Invalid referral code: {code}")
            return False

        if link.status not in [ReferralStatus.PENDING, ReferralStatus.CONVERTED]:
            logger.warning(f"Referral link {code} is {link.status.value}")
            return False

        # Check expiry
        expires = datetime.fromisoformat(link.expires_at)
        if datetime.utcnow() > expires:
            link.status = ReferralStatus.EXPIRED
            return False

        # Add referred contact if not already added
        if referred_contact_id not in link.referred_contacts:
            link.referred_contacts.append(referred_contact_id)
            link.conversion_count += 1
            link.status = ReferralStatus.CONVERTED
            logger.info(f"[v] Referral converted: {link.referrer_contact_id} referred {referred_contact_id}")

            # Queue reward processing
            program = self.get_program(link.program_id)
            if program:
                self._rewards_pending.append({
                    "link_code": code,
                    "program_id": link.program_id,
                    "referrer": link.referrer_contact_id,
                    "referred": referred_contact_id,
                    "reward_type": program.reward_type.value,
                    "reward_value": program.reward_value,
                    "reward_description": program.reward_description,
                    "created_at": datetime.utcnow().isoformat(),
                })

            return True
        return False

    def claim_reward(self, link_code: str) -> Optional[Dict]:
        """Claim a reward for a referral link"""
        link = self.get_link(link_code)
        if not link or link.reward_claimed:
            return None

        program = self.get_program(link.program_id)
        if not program:
            return None

        reward = {
            "type": program.reward_type.value,
            "value": program.reward_value,
            "description": program.reward_description,
            "contact_id": link.referrer_contact_id,
            "claimed_at": datetime.utcnow().isoformat(),
        }

        link.reward_claimed = True
        link.status = ReferralStatus.REWARDED
        logger.info(f"[v] Reward claimed: {link.referrer_contact_id} got {reward['description']}")
        return reward

    def get_stats(self, client_id: int = 1) -> Dict:
        """Get aggregate referral statistics"""
        client_links = [
            l for l in self.links.values()
            if l.client_id == client_id
        ]
        total_referrals = sum(len(l.referred_contacts) for l in client_links)
        total_converted = sum(1 for l in client_links if l.conversion_count > 0)

        return {
            "total_links_created": len(client_links),
            "total_referrals": total_referrals,
            "total_converted": total_converted,
            "conversion_rate": round(
                (total_converted / max(len(client_links), 1)) * 100, 1
            ),
            "rewards_claimed": sum(1 for l in client_links if l.reward_claimed),
            "active_programs": sum(
                1 for p in self.programs.values()
                if p.client_id == client_id and p.is_active
            ),
        }

    def get_contact_stats(self, contact_id: str, client_id: int = 1) -> Dict:
        """Get referral stats for a specific contact"""
        contact_links = [
            l for l in self.links.values()
            if l.referrer_contact_id == contact_id and l.client_id == client_id
        ]
        return {
            "total_links": len(contact_links),
            "total_referrals": sum(len(l.referred_contacts) for l in contact_links),
            "conversions": sum(1 for l in contact_links if l.conversion_count > 0),
            "rewards_claimed": sum(1 for l in contact_links if l.reward_claimed),
            "links": [l.to_dict() for l in contact_links],
        }


# Global referral system instance
referral_system = ReferralSystem()