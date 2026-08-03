"""
Business Profile Management — Restaurant, Hotel, Doctor, CA, Lawyer, Salon templates
"""
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("business_profiles")


class BusinessType(Enum):
    RESTAURANT = "restaurant"
    HOTEL = "hotel"
    DOCTOR = "doctor"
    CA = "ca"
    LAWYER = "lawyer"
    SALON = "salon"
    RETAIL = "retail"
    EDUCATION = "education"
    CUSTOM = "custom"


@dataclass
class BusinessProfile:
    """A business profile with branding, templates, and settings"""
    id: str
    client_id: int
    owner_id: str
    business_type: BusinessType
    name: str
    description: str = ""
    logo_url: str = ""
    primary_color: str = "#25D366"
    secondary_color: str = "#128C7E"
    welcome_message: str = ""
    working_hours: Dict[str, str] = field(default_factory=dict)
    contact_phone: str = ""
    contact_email: str = ""
    address: str = ""
    website: str = ""
    payment_methods: List[str] = field(default_factory=lambda: ["cash", "upi"])
    delivery_enabled: bool = False
    delivery_radius_km: int = 5
    tax_rate_percent: float = 5.0
    currency: str = "INR"
    language: str = "hi_en"  # hi, en, hi_en
    is_active: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "client_id": self.client_id,
            "owner_id": self.owner_id,
            "business_type": self.business_type.value,
            "name": self.name,
            "description": self.description,
            "logo_url": self.logo_url,
            "primary_color": self.primary_color,
            "secondary_color": self.secondary_color,
            "welcome_message": self.welcome_message,
            "working_hours": self.working_hours,
            "contact_phone": self.contact_phone,
            "contact_email": self.contact_email,
            "address": self.address,
            "website": self.website,
            "payment_methods": self.payment_methods,
            "delivery_enabled": self.delivery_enabled,
            "delivery_radius_km": self.delivery_radius_km,
            "tax_rate_percent": self.tax_rate_percent,
            "currency": self.currency,
            "language": self.language,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CatalogItem:
    """A product/service in the catalog"""
    id: str
    business_id: str
    category: str
    name: str
    description: str = ""
    price: float = 0.0
    image_url: str = ""
    is_available: bool = True
    tags: List[str] = field(default_factory=list)
    variants: Dict[str, Any] = field(default_factory=dict)  # size, spice_level, etc.
    sort_order: int = 0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "business_id": self.business_id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "price": self.price,
            "image_url": self.image_url,
            "is_available": self.is_available,
            "tags": self.tags,
            "variants": self.variants,
            "sort_order": self.sort_order,
            "created_at": self.created_at,
        }


@dataclass
class Order:
    """A customer order"""
    id: str
    business_id: str
    customer_phone: str
    customer_name: str = ""
    items: List[Dict] = field(default_factory=list)  # [{item_id, name, qty, price}]
    subtotal: float = 0.0
    tax_amount: float = 0.0
    total: float = 0.0
    status: str = "pending"  # pending, confirmed, preparing, ready, delivered, cancelled
    payment_method: str = "cash"
    payment_status: str = "pending"  # pending, paid, failed, refunded
    delivery_address: str = ""
    notes: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "business_id": self.business_id,
            "customer_phone": self.customer_phone,
            "customer_name": self.customer_name,
            "items": self.items,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "total": self.total,
            "status": self.status,
            "payment_method": self.payment_method,
            "payment_status": self.payment_status,
            "delivery_address": self.delivery_address,
            "notes": self.notes,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class BusinessTemplate:
    """Pre-built templates for each business type"""

    TEMPLATES = {
        BusinessType.RESTAURANT: {
            "name": "Restaurant",
            "icon": "🍽️",
            "welcome": "🍽️ {business_name} mein aapka swagat hai!\n\nAaj kya order karna chahenge? Menu dekhne ke liye 'Menu' batao.",
            "categories": ["Starters", "Main Course", "Breads", "Rice & Biryani", "Desserts", "Beverages"],
            "order_prompt": "Kitna {item_name} chahiye?",
            "confirmation": "✅ Order #{order_id} confirm!\n\nItems:\n{items}\nTotal: ₹{total}\nTime: {time} min\n\nKuch aur chahiye?",
            "status_updates": {
                "preparing": "👨‍🍳 Aapka order taiyar ho raha hai...",
                "ready": "✅ Order ready! Delivery:[delivery_details]",
                "delivered": "🙏 Thank you! Kuch aur chahiye toh batao",
            },
            "fields": ["table_number", "dine_in", "spice_level"],
        },
        BusinessType.HOTEL: {
            "name": "Hotel",
            "icon": "🏨",
            "welcome": "🏨 {business_name}\n\nRoom booking ke liye kya chahiye?\nSingle Room - ₹{single_price}\nDouble Room - ₹{double_price}\nSuite - ₹{suite_price}",
            "categories": ["Single Room", "Double Room", "Suite", "Deluxe Room", "Family Room"],
            "order_prompt": "Kon sa room type chahiye aur kab check-in karna hai?",
            "confirmation": "✅ Booking #{order_id} confirmed!\nRoom: {room_type}\nCheck-in: {checkin}\nCheck-out: {checkout}\nGuests: {guests}\nTotal: ₹{total}",
            "status_updates": {
                "confirmed": "✅ Room booked! Check-in 2 PM se shuru hota hai",
                "checked_in": "🏨 Welcome! Aapka room number #{room_number} hai",
                "checked_out": "🙏 Thank you! Phir se aane ke liye shukriya",
            },
            "fields": ["checkin_date", "checkout_date", "guests", "special_requests"],
        },
        BusinessType.DOCTOR: {
            "name": "Doctor/Clinic",
            "icon": "🩺",
            "welcome": "🩺 {business_name} Clinic\n\nKya problem hai aapko?\nYa appointment book karna chahte ho?\n\nEmergency: 108",
            "categories": ["General Medicine", "Pediatrics", "Cardiology", "Orthopedics", "Dental", "Eye", "Skin"],
            "order_prompt": "Kya symptoms hai? Ya appointment ke liye date batao",
            "confirmation": "✅ Appointment #{order_id} booked!\nDoctor: {doctor_name}\nDate: {date}\nTime: {time}\nPatient: {patient_name}\n\n24hr pehle reminder aayega",
            "status_updates": {
                "confirmed": "✅ Appointment confirmed! Pahunchne se 30 min pehle clinic hona chahiye",
                "completed": "✅ Appointment done! Follow-up chahiye toh batao",
                "cancelled": "❌ Appointment cancelled. Reschedule ke liye 'Book' type karein",
            },
            "fields": ["patient_name", "age", "gender", "symptoms", "doctor_preference"],
        },
        BusinessType.CA: {
            "name": "Chartered Accountant",
            "icon": "📊",
            "welcome": "📊 {business_name} & Associates\n\nKaise madad kar sakte hain?\n\nServices:\n- ITR Filing\n- GST Return\n- Audit\n- Company Registration\n\nKya chahiye aapko?",
            "categories": ["ITR Filing", "GST Return", "TDS Return", "Audit", "Company Registration", "Tax Planning"],
            "order_prompt": "Konsa service chahiye? Client details batao",
            "confirmation": "✅ Service request #{order_id} received!\nService: {service_name}\nClient: {client_name}\nDeadline: {deadline}\n\nTeam aapko 24hrs mein call karegi",
            "status_updates": {
                "in_progress": "⏳ Work in progress... aapko update diya jayega",
                "completed": "✅ Service completed! Documents uploaded hai",
                "pending_docs": "📄 Kuch documents chahiye: {required_docs}",
            },
            "fields": ["client_name", "pan_number", "financial_year", "turnover", "documents_uploaded"],
        },
        BusinessType.LAWYER: {
            "name": "Lawyer/Legal",
            "icon": "⚖️",
            "welcome": "⚖️ {business_name} Law Offices\n\nLegal consultation ke liye kya chahiye aapko?\n\nDisclaimer: Yeh legal advice nahi hai, sirf information ke liye hai",
            "categories": ["Property", "Divorce", "Criminal", "Corporate", "Civil", "Family", "Cheque Bounce"],
            "order_prompt": "Apna case type batayein aur kya documentation hai?",
            "confirmation": "✅ Consultation booked!\nCase Type: {case_type}\nDate: {date}\nLawyer: {lawyer_name}\n\nDisclaimer: Legal advice nahi hai",
            "status_updates": {
                "consultation_scheduled": "📅 Consultation scheduled! Documents leke aayega",
                "case_filed": "📋 Case filed! Case number: {case_number}",
                "closed": "✅ Case closed. Agar koi aur ho toh batao",
            },
            "fields": ["case_type", "urgency", "opponent_name", "court_name", "documents_uploaded"],
        },
        BusinessType.SALON: {
            "name": "Salon/Beauty",
            "icon": "💇",
            "welcome": "💇 {business_name} Salon & Spa\n\nKya service leni hai aapko?\n\nHaircut, Facial, Massage, Manicure, Pedicure",
            "categories": ["Haircut", "Facial", "Massage", "Manicure", "Pedicure", "Bridal Package", "Hair Coloring"],
            "order_prompt": "Kon si service chahiye aur kab appointment chahiye?",
            "confirmation": "✅ Appointment #{order_id} booked!\nService: {service_name}\nDate: {date}\nTime: {time}\nStylist: {stylist_name}\n\nReminder 1hr pehle aayega!",
            "status_updates": {
                "confirmed": "✅ Appointment confirmed! Cancel karne se pehle 2hr pehle batao",
                "completed": "✨ Service done! Feedback dein",
                "cancelled": "❌ Appointment cancelled. Phir se book kar sakte ho",
            },
            "fields": ["stylist_preference", "gender", "hair_type", "skin_sensitivity"],
        },
        BusinessType.RETAIL: {
            "name": "Retail Shop",
            "icon": "🛍️",
            "welcome": "🛍️ {business_name}\n\nAaj kya kharidna chahte ho?\nCategories dekhein ya direct search karein",
            "categories": ["Electronics", "Clothing", "Groceries", "Home & Kitchen", "Beauty", "Toys"],
            "order_prompt": "Product ka naam batao ya category select karein",
            "confirmation": "✅ Order #{order_id} placed!\nItems:\n{items}\nTotal: ₹{total}\nDelivery: {delivery_date}\n\nThank you for shopping! 🛍️",
            "status_updates": {
                "packed": "📦 Order packed! Delivery aapke ghar ja raha hai",
                "delivered": "✅ Delivered! Feedback dein",
                "return_requested": "↩️ Return request received. Team aapko contact karegi",
            },
            "fields": ["size", "color", "brand_preference", "gift_wrap"],
        },
        BusinessType.EDUCATION: {
            "name": "Education/Tuition",
            "icon": "📚",
            "welcome": "📚 {business_name}\n\nAdmission liye hai ya doubt poochna hai?\nCourses, Fees, Schedule ke baare mein poocho",
            "categories": ["Class 1-5", "Class 6-10", "Class 11-12", "JEE/NEET", "Spoken English", "Computer"],
            "order_prompt": "Konsa course chahiye? Student ka naam aur class batao",
            "confirmation": "✅ Admission #{order_id} taken!\nCourse: {course_name}\nStudent: {student_name}\nBatch: {batch_time}\nFees: ₹{fees}\n\nFirst class: {start_date}",
            "status_updates": {
                "admission_confirmed": "✅ Admission confirmed! Fees pay karein",
                "class_scheduled": "📅 Class scheduled! Link send ho jayega",
                "completed": "🎓 Course completed! Certificate mil jayega",
            },
            "fields": ["student_name", "class", "school_name", "guardian_phone", "batch_preference"],
        },
        BusinessType.CUSTOM: {
            "name": "Custom Business",
            "icon": "💼",
            "welcome": "👋 {business_name} mein aapka swagat hai!\nKya chahiye aapko?",
            "categories": ["Service 1", "Service 2", "Service 3"],
            "order_prompt": "Apna requirement batayein",
            "confirmation": "✅ Request #{order_id} received! Hum aapko jald se jald contact karenge",
            "status_updates": {},
            "fields": ["custom_field_1", "custom_field_2"],
        },
    }

    @classmethod
    def get_template(cls, business_type: BusinessType) -> Dict:
        return cls.TEMPLATES.get(business_type, cls.TEMPLATES[BusinessType.CUSTOM])

    @classmethod
    def list_types(cls) -> List[Dict]:
        return [
            {"type": bt.value, "name": cls.TEMPLATES[bt]["name"], "icon": cls.TEMPLATES[bt]["icon"]}
            for bt in BusinessType if bt != BusinessType.CUSTOM
        ]


class BusinessManager:
    """Manage business profiles, catalogs, and orders"""

    def __init__(self):
        self.profiles: Dict[str, BusinessProfile] = {}  # id -> profile
        self.catalogs: Dict[str, List[CatalogItem]] = {}  # business_id -> items
        self.orders: Dict[str, List[Order]] = {}  # business_id -> orders

    def create_profile(self, profile: BusinessProfile) -> BusinessProfile:
        self.profiles[profile.id] = profile
        logger.info(f"[+] Business created: {profile.name} ({profile.business_type.value})")
        return profile

    def get_profile(self, business_id: str) -> Optional[BusinessProfile]:
        return self.profiles.get(business_id)

    def update_profile(self, business_id: str, **kwargs) -> Optional[BusinessProfile]:
        profile = self.profiles.get(business_id)
        if not profile:
            return None
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.updated_at = datetime.utcnow().isoformat()
        return profile

    def add_catalog_item(self, business_id: str, item: CatalogItem) -> CatalogItem:
        if business_id not in self.catalogs:
            self.catalogs[business_id] = []
        self.catalogs[business_id].append(item)
        logger.info(f"[+] Catalog item added: {item.name} for {business_id}")
        return item

    def get_catalog(self, business_id: str, category: str = "") -> List[Dict]:
        items = self.catalogs.get(business_id, [])
        if category:
            items = [i for i in items if i.category == category]
        return [i.to_dict() for i in items]

    def get_categories(self, business_id: str) -> List[str]:
        items = self.catalogs.get(business_id, [])
        return list(dict.fromkeys([i.category for i in items]))  # unique, preserve order

    def create_order(self, business_id: str, order: Order) -> Order:
        if business_id not in self.orders:
            self.orders[business_id] = []
        self.orders[business_id].append(order)
        logger.info(f"[+] Order created: {order.id} for {business_id}")
        return order

    def get_orders(self, business_id: str, status: str = "") -> List[Dict]:
        orders = self.orders.get(business_id, [])
        if status:
            orders = [o for o in orders if o.status == status]
        return [o.to_dict() for o in orders]

    def update_order_status(self, business_id: str, order_id: str, status: str) -> bool:
        orders = self.orders.get(business_id, [])
        for order in orders:
            if order.id == order_id:
                order.status = status
                order.updated_at = datetime.utcnow().isoformat()
                return True
        return False

    def get_business_stats(self, business_id: str) -> Dict:
        orders = self.orders.get(business_id, [])
        return {
            "total_orders": len(orders),
            "pending": sum(1 for o in orders if o.status == "pending"),
            "completed": sum(1 for o in orders if o.status == "delivered"),
            "revenue": sum(o.total for o in orders if o.payment_status == "paid"),
            "avg_order_value": round(sum(o.total for o in orders) / max(len(orders), 1), 1),
        }


# Global manager
business_manager = BusinessManager()