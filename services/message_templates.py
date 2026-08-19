"""
Message Templates — Profession-specific WhatsApp message templates with variables

Provides:
- Pre-built message templates for each business vertical (doctor, lawyer, restaurant, etc.)
- Template variable rendering ({{customer_name}}, {{date}}, {{time}}, {{amount}}, {{service}}, {{business_name}})
- Image + text combo support for rich messages
- Bulk send with personalization
"""
import os
import json
import re
import logging
from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("message_templates")


class TemplateCategory(str, Enum):
    WELCOME = "welcome"
    APPOINTMENT_CONFIRMED = "appointment_confirmed"
    APPOINTMENT_REMINDER = "appointment_reminder"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    ORDER_CONFIRMED = "order_confirmed"
    ORDER_DELIVERED = "order_delivered"
    INVOICE = "invoice"
    PAYMENT_LINK = "payment_link"
    FOLLOW_UP = "follow_up"
    PROMOTION = "promotion"
    REFUND = "refund"
    PRESCRIPTION = "prescription"
    RECEIPT = "receipt"
    TEST_RESULT = "test_result"


@dataclass
class TemplateVariable:
    name: str
    required: bool = True
    description: str = ""


SUPPORTED_VARIABLES: Dict[str, TemplateVariable] = {
    "customer_name": TemplateVariable("customer_name", True, "Customer's full name"),
    "business_name": TemplateVariable("business_name", True, "Business/practice name"),
    "date": TemplateVariable("date", True, "Appointment or service date"),
    "time": TemplateVariable("time", True, "Appointment or service time"),
    "amount": TemplateVariable("amount", True, "Monetary amount (with currency)"),
    "service": TemplateVariable("service", True, "Service or product name"),
    "service_name": TemplateVariable("service_name", False, "Specific service name"),
    "doctor_name": TemplateVariable("doctor_name", False, "Doctor's name"),
    "patient_name": TemplateVariable("patient_name", False, "Patient's name"),
    "order_id": TemplateVariable("order_id", True, "Order or booking reference number"),
    "duration": TemplateVariable("duration", False, "Duration of appointment/service"),
    "address": TemplateVariable("address", False, "Business or delivery address"),
    "phone": TemplateVariable("phone", False, "Contact phone number"),
    "email": TemplateVariable("email", False, "Contact email"),
    "styling": TemplateVariable("styling", False, "Hair styling or beauty service name"),
    "stylist_name": TemplateVariable("stylist_name", False, "Assigned stylist name"),
    "table_number": TemplateVariable("table_number", False, "Table number"),
    "items": TemplateVariable("items", True, "List of items ordered"),
    "total": TemplateVariable("total", True, "Total amount due"),
    "delivery_date": TemplateVariable("delivery_date", False, "Expected delivery date"),
    "checkin": TemplateVariable("checkin", False, "Check-in date"),
    "checkout": TemplateVariable("checkout", False, "Check-out date"),
    "room_type": TemplateVariable("room_type", False, "Room type booked"),
    "guests": TemplateVariable("guests", False, "Number of guests"),
    "deadline": TemplateVariable("deadline", False, "Service deadline"),
    "student_name": TemplateVariable("student_name", False, "Student name"),
    "course_name": TemplateVariable("course_name", False, "Course/program name"),
    "fees": TemplateVariable("fees", False, "Fee amount"),
    "start_date": TemplateVariable("start_date", False, "Course start date"),
    "batch_time": TemplateVariable("batch_time", False, "Batch timing"),
    "case_type": TemplateVariable("case_type", False, "Legal case type"),
    "lawyer_name": TemplateVariable("lawyer_name", False, "Assigned lawyer"),
    "case_number": TemplateVariable("case_number", False, "Case reference number"),
    "pan_number": TemplateVariable("pan_number", False, "PAN number"),
    "financial_year": TemplateVariable("financial_year", False, "Financial year"),
    "turnover": TemplateVariable("turnover", False, "Annual turnover"),
    "required_docs": TemplateVariable("required_docs", False, "Required documents list"),
    "discount": TemplateVariable("discount", False, "Discount percentage or amount"),
    "otp": TemplateVariable("otp", False, "One-time password"),
    "rating_url": TemplateVariable("rating_url", False, "Rating/feedback link"),
}


@dataclass
class MessageTemplate:
    id: str
    business_type: str
    category: TemplateCategory
    title: str
    content: str
    variables: List[str] = field(default_factory=list)
    language: str = "hi_en"
    description: str = ""
    image_url: Optional[str] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "business_type": self.business_type,
            "category": self.category.value if isinstance(self.category, TemplateCategory) else self.category,
            "title": self.title,
            "content": self.content,
            "variables": self.variables,
            "language": self.language,
            "description": self.description,
            "image_url": self.image_url,
            "is_active": self.is_active,
        }


class TemplateEngine:
    """
    Pre-built message templates for each business vertical.
    Supports variable rendering, image+text combos, and bulk personalization.
    """

    PROFESSION_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
        "doctor": [
            {
                "id": "doctor_appt_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Appointment Confirmation",
                "description": "Sent when a patient books an appointment",
                "content": "🩺 *{{business_name}} - Appointment Confirmed*\n\nनमस्ते {{customer_name}}!\n\nआपका appointment confirm हो गया है:\n\n📅 तारीख: {{date}}\n⏰ समय: {{time}}\n👨‍⚕️ डॉक्टर: {{doctor_name}}\n🏥 प्रेशिप्शन फॉर्म: {{service}}\n⏱️ अवधि: {{duration}}\nबुक करने वाला आईडी: {{order_id}}\n\nकृपया 30 मिनट पहले पहुँचें।\nकोई सवाल हैं? कॉल करें: {{phone}}",
                "variables": ["customer_name", "business_name", "date", "time", "doctor_name", "service", "duration", "order_id", "phone"],
                "image_url": None,
            },
            {
                "id": "doctor_appt_reminder",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Appointment Reminder",
                "description": "24-hour reminder before appointment",
                "content": "🔔 *{{business_name}} - Appointment Reminder*\n\nनमस्ते {{customer_name}}!\n\nआपका appointment कल है:\n\n📅 {{date}}\n⏰ {{time}}\n👨‍⚕️ {{doctor_name}}\n\nकृपया समय पर आएँ। अगर cancel करना है तो जल्दी बताएं।",
                "variables": ["customer_name", "business_name", "date", "time", "doctor_name"],
                "image_url": "https://api.qrserver.com/v1/api-qr/?size=150x150&data={{business_name}}_appointment",
            },
            {
                "id": "doctor_prescription",
                "category": TemplateCategory.PRESCRIPTION,
                "title": "Prescription Ready",
                "description": "Sent when prescription is ready for pickup",
                "content": "🩺 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपकी prescription तैयार है। डॉक्टर ने लिखी दवा:\n\n{{service}}\n\nफार्मेसी में ले जाएँ।\n\nधन्यवाद!\n{{doctor_name}}",
                "variables": ["customer_name", "business_name", "doctor_name", "service"],
                "image_url": "https://api.qrserver.com/v1/api-qr/?size=150x150&data=prescription",
            },
            {
                "id": "doctor_test_result",
                "category": TemplateCategory.TEST_RESULT,
                "title": "Test Results Available",
                "description": "Notification when lab results are ready",
                "content": "📋 *{{business_name}} - Test Report*\n\nनमस्ते {{customer_name}}!\n\nआपका टेस्ट रिपोर्ट तैयार है।\n\n{{service}}\n\nप्लीस नोट करें। अगर कोई सवाल हो तो बेझिझक पूछें।\n\n👨‍⚕️ {{doctor_name}}",
                "variables": ["customer_name", "business_name", "doctor_name", "service"],
                "image_url": None,
            },
            {
                "id": "doctor_followup",
                "category": TemplateCategory.FOLLOW_UP,
                "title": "Follow-up Reminder",
                "description": "Post-appointment follow-up",
                "content": "🙏 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nहम आशा करते हैं आपका अपpointemnt अच्छा गया होगा।\n\nअगर कोई side effects या सवाल हैं, तो कृपया संपर्क करें।\n\nFollow-up appointment के लिए 'Follow-up' टाइप करें।\n\nधन्यवाद! 🙏",
                "variables": ["customer_name", "business_name"],
                "image_url": None,
            },
        ],
        "ca": [
            {
                "id": "ca_service_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Service Request Confirmed",
                "description": "Sent when a CA service request is received",
                "content": "📊 *{{business_name}} & Associates*\n\nनमस्ते {{customer_name}}!\n\nआपका service request confirm हो गया है:\n\n🧾 सेवा: {{service}}\n📅 डेडलाइन: {{date}}\n💰 Amount: {{amount}}\nरेफ़रेंस: {{order_id}}\n\nहम आपको 24 घंटे में कॉल करेंगे।",
                "variables": ["customer_name", "business_name", "service", "date", "amount", "order_id"],
                "image_url": None,
            },
            {
                "id": "ca_tax_reminder",
                "category": TemplateCategory.PAYMENT_LINK,
                "title": "Tax Payment Reminder",
                "description": "Reminder for pending tax payments",
                "content": "🔔 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका tax payment {{amount}} pending है।\n\nडेडलाइन: {{date}}\n\nPayment link: {{service}}\n\nकृपया समय पर भुगतान करें।",
                "variables": ["customer_name", "business_name", "amount", "date", "service"],
                "image_url": None,
            },
            {
                "id": "ca_document_request",
                "category": TemplateCategory.FOLLOW_UP,
                "title": "Document Request",
                "description": "Request additional documents from client",
                "content": "📄 *{{business_name}} - Documents Required*\n\nनमस्ते {{customer_name}}!\n\n{{service}} के लिए कुछ documents चाहिए:\n\n{{required_docs}}\n\nकृपया अपलोड करें या भेजें।\n\nधन्यवाद!",
                "variables": ["customer_name", "business_name", "service", "required_docs"],
                "image_url": None,
            },
        ],
        "lawyer": [
            {
                "id": "lawyer_consult_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Legal Consultation Confirmed",
                "description": "Sent when consultation is booked",
                "content": "⚖️ *{{business_name}} Law Offices*\n\nनमस्ते {{customer_name}}!\n\nआपका consultation confirm हो गया है:\n\n📅 Date: {{date}}\n⏰ Time: {{time}}\n👨‍💼 Lawyer: {{lawyer_name}}\n📋 Case: {{service}}\nरेफ़रेंस: {{order_id}}\n\nDisclaimer: यह legal advice नहीं है।",
                "variables": ["customer_name", "business_name", "date", "time", "lawyer_name", "service", "order_id"],
                "image_url": None,
            },
            {
                "id": "lawyer_case_update",
                "category": TemplateCategory.FOLLOW_UP,
                "title": "Case Status Update",
                "description": "Update on case progress",
                "content": "📋 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपके case ({{case_number}}) का अपडेट:\n\n{{service}}\n\n{{amount}}\n\nअगला कदम: {{date}}\n\nकोई सवाल हैं? कॉल करें: {{phone}}",
                "variables": ["customer_name", "business_name", "case_number", "service", "amount", "date", "phone"],
                "image_url": None,
            },
            {
                "id": "lawyer_court_notice",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Court Date Reminder",
                "description": "Reminds about upcoming court date",
                "content": "🏛️ *{{business_name}} - Court Reminder*\n\nनमस्ते {{customer_name}}!\n\nआपका court date है:\n\n📅 {{date}}\n⏰ {{time}}\n🏛️ Court: {{service}}\nCase No: {{case_number}}\n\nकृपया समय पर पहुँचें।",
                "variables": ["customer_name", "business_name", "date", "time", "service", "case_number"],
                "image_url": None,
            },
        ],
        "restaurant": [
            {
                "id": "restaurant_order_confirm",
                "category": TemplateCategory.ORDER_CONFIRMED,
                "title": "Order Confirmation",
                "description": "Sent when an order is placed",
                "content": "🍽️ *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका order confirm हो गया:\n\n{{items}}\nTotal: {{amount}}\n⏱️ Time: {{duration}}\nOrder ID: {{order_id}}\n\nThank you! 🙏",
                "variables": ["customer_name", "business_name", "items", "amount", "duration", "order_id"],
                "image_url": None,
            },
            {
                "id": "restaurant_order_ready",
                "category": TemplateCategory.ORDER_DELIVERED,
                "title": "Order Ready for Pickup/Delivery",
                "description": "Notification when order is ready",
                "content": "✅ *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका order तैयार है:\n\nOrder ID: {{order_id}}\n{{service}}\n\nDelivery me: {{delivery_date}}\nया pickup कर सकते हैं।",
                "variables": ["customer_name", "business_name", "order_id", "service", "delivery_date"],
                "image_url": None,
            },
            {
                "id": "restaurant_invoice",
                "category": TemplateCategory.INVOICE,
                "title": "Invoice / Receipt",
                "description": "Invoice with breakdown",
                "content": "🧾 *{{business_name}} - Invoice*\n\nनमस्ते {{customer_name}}!\n\nInvoice Details:\n{{items}}\n\nSubtotal: {{amount}}\nTax: {{service}}\nTotal: {{total}}\n\nPayment: {{phone}}\nधन्यवाद!",
                "variables": ["customer_name", "business_name", "items", "amount", "service", "total", "phone"],
                "image_url": "https://api.qrserver.com/v1/api-qr/?size=200x200&data={{business_name}}_invoice_{{order_id}}",
            },
        ],
        "salon": [
            {
                "id": "salon_appt_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Salon Appointment Confirmation",
                "description": "Sent when appointment is booked",
                "content": "💇 *{{business_name}} Salon & Spa*\n\nनमस्ते {{customer_name}}!\n\nआपका appointment confirm हो गया:\n\n✂️ Service: {{service}}\n📅 Date: {{date}}\n⏰ Time: {{time}}\n💇 Stylist: {{stylist_name}}\nरेफ़रेंस: {{order_id}}\n\n1 घंटे पहले reminder मिलेगा।",
                "variables": ["customer_name", "business_name", "service", "date", "time", "stylist_name", "order_id"],
                "image_url": None,
            },
            {
                "id": "salon_appt_reminder",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Salon Appointment Reminder",
                "description": "1-hour before appointment",
                "content": "🔔 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका appointment आज {{time}} है:\n\n{{service}} with {{stylist_name}}\n\n कैंसल करने के लिए 2 घंटे पहले बताएं।",
                "variables": ["customer_name", "business_name", "service", "time", "stylist_name"],
                "image_url": None,
            },
            {
                "id": "salon_after_service",
                "category": TemplateCategory.FOLLOW_UP,
                "title": "After Service Follow-up",
                "description": "Post-service feedback request",
                "content": "✨ *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपकी {{service}} खत्म हो गई है।\n\nअगर आपको पसंद आई हो तो 5-star rating दें:\n{{amount}}\n\nआपका feedback हमारे लिए महत्वपूर्ण है! 💖",
                "variables": ["customer_name", "business_name", "service", "amount"],
                "image_url": None,
            },
        ],
        "hotel": [
            {
                "id": "hotel_booking_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Booking Confirmation",
                "description": "Sent when a room is booked",
                "content": "🏨 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका booking confirm हो गया:\n\nRoom: {{service}}\nCheck-in: {{date}}\nCheck-out: {{time}}\nGuests: {{guests}}\nTotal: {{amount}}\nBooking ID: {{order_id}}\n\nCheck-in 2 PM से शुरू होगा।",
                "variables": ["customer_name", "business_name", "service", "date", "time", "guests", "amount", "order_id"],
                "image_url": None,
            },
            {
                "id": "hotel_checkin_info",
                "category": TemplateCategory.WELCOME,
                "title": "Check-in Information",
                "description": "Details for check-in day",
                "content": "🏨 *Welcome to {{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका room तैयार है:\n\nRoom No: {{service}}\nLocation: {{address}}\n\nWiFi: {{phone}}\n\nEnjoy your stay! 🏨",
                "variables": ["customer_name", "business_name", "service", "address", "phone"],
                "image_url": None,
            },
            {
                "id": "hotel_checkout_reminder",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Check-out Reminder",
                "description": "Reminds about checkout time",
                "content": "🔔 *{{business_name}} - Check-out Reminder*\n\nनमस्ते {{customer_name}}!\n\nआपका check-out है: {{date}}\nTime: {{time}}\n\nLate checkout के लिए contact करें।\n\nधन्यवाद!\n{{business_name}}",
                "variables": ["customer_name", "business_name", "date", "time"],
                "image_url": None,
            },
        ],
        "retail": [
            {
                "id": "retail_order_confirm",
                "category": TemplateCategory.ORDER_CONFIRMED,
                "title": "Order Confirmation",
                "description": "Sent when an order is placed",
                "content": "🛍️ *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका order confirm हो गया:\n\n{{items}}\nTotal: {{amount}}\nDelivery: {{delivery_date}}\nOrder ID: {{order_id}}\n\nTrack करने के लिए order ID use करें।",
                "variables": ["customer_name", "business_name", "items", "amount", "delivery_date", "order_id"],
                "image_url": None,
            },
            {
                "id": "retail_order_shipped",
                "category": TemplateCategory.ORDER_DELIVERED,
                "title": "Order Shipped",
                "description": "Notification when order is shipped",
                "content": "📦 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका order भेज दिया गया:\n\nOrder ID: {{order_id}}\n{{service}}\n\nTracking: {{amount}}\nDelivery: {{delivery_date}}\n\nधन्यवाद!",
                "variables": ["customer_name", "business_name", "order_id", "service", "amount", "delivery_date"],
                "image_url": None,
            },
            {
                "id": "retail_invoice",
                "category": TemplateCategory.INVOICE,
                "title": "Invoice / Receipt",
                "description": "Invoice with payment details",
                "content": "🧾 *{{business_name}} - Receipt*\n\nनमस्ते {{customer_name}}!\n\nReceipt for Order #{{order_id}}:\n\n{{items}}\n\nSubtotal: {{amount}}\nTax: {{service}}\nTotal: {{total}}\n\nPayment via UPI: {{phone}}\nधन्यवाद!",
                "variables": ["customer_name", "business_name", "order_id", "items", "amount", "service", "total", "phone"],
                "image_url": "https://api.qrserver.com/v1/api-qr/?size=200x200&data={{business_name}}_receipt_{{order_id}}",
            },
        ],
        "education": [
            {
                "id": "edu_admission_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Admission Confirmation",
                "description": "Sent when admission is confirmed",
                "content": "📚 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका admission confirm हो गया:\n\nCourse: {{service}}\nStudent: {{student_name}}\nBatch: {{batch_time}}\nFees: {{amount}}\nAdmission ID: {{order_id}}\n\nFirst class: {{date}}\n\nWelcome aboard! 🎓",
                "variables": ["customer_name", "business_name", "service", "student_name", "batch_time", "amount", "order_id", "date"],
                "image_url": None,
            },
            {
                "id": "edu_class_reminder",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Class Reminder",
                "description": "Daily class reminder",
                "content": "📅 *{{business_name}} - Class Reminder*\n\nनमस्ते {{customer_name}}!\n\nआज की class:\n\n📚 Subject: {{service}}\n⏰ Time: {{time}}\n📍 Location: {{address}}\n\nLive link: {{amount}}\n\nनोट्स download करना मत भूलिए।",
                "variables": ["customer_name", "business_name", "service", "time", "address", "amount"],
                "image_url": None,
            },
            {
                "id": "edu_payment_reminder",
                "category": TemplateCategory.PAYMENT_LINK,
                "title": "Fee Payment Reminder",
                "description": "Reminder for pending fees",
                "content": "💰 *{{business_name}} - Fee Reminder*\n\nनमस्ते {{customer_name}}!\n\nPending fees: {{amount}}\nDue: {{date}}\n\nPayment link: {{service}}\n\nकृपया समय पर भुगतान करें।",
                "variables": ["customer_name", "business_name", "amount", "date", "service"],
                "image_url": None,
            },
        ],
        "salon": [
            {
                "id": "salon_appt_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Salon Appointment Confirmation",
                "description": "Sent when appointment is booked",
                "content": "💇 *{{business_name}} Salon & Spa*\n\nनमस्ते {{customer_name}}!\n\nआपका appointment confirm हो गया:\n\n✂️ Service: {{service}}\n📅 Date: {{date}}\n⏰ Time: {{time}}\n💇 Stylist: {{stylist_name}}\nरेफ़रेंस: {{order_id}}\n\n1 घंटे पहले reminder मिलेगा।",
                "variables": ["customer_name", "business_name", "service", "date", "time", "stylist_name", "order_id"],
                "image_url": None,
            },
            {
                "id": "salon_appt_reminder",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Salon Appointment Reminder",
                "description": "1-hour before appointment",
                "content": "🔔 *{{business_name}}*\n\nनमस्ते {{customer_name}}!\n\nआपका appointment आज {{time}} है:\n\n{{service}} with {{stylist_name}}\n\nकैंसल करने के लिए 2 घंटे पहले बताएं।",
                "variables": ["customer_name", "business_name", "service", "time", "stylist_name"],
                "image_url": None,
            },
        ],
        "lawyer": [
            {
                "id": "lawyer_consult_confirm",
                "category": TemplateCategory.APPOINTMENT_CONFIRMED,
                "title": "Legal Consultation Confirmed",
                "description": "Sent when consultation is booked",
                "content": "⚖️ *{{business_name}} Law Offices*\n\nनमस्ते {{customer_name}}!\n\nआपका consultation confirm हो गया है:\n\n📅 Date: {{date}}\n⏰ Time: {{time}}\n👨‍💼 Lawyer: {{lawyer_name}}\n📋 Case: {{service}}\nरेफ़रेंस: {{order_id}}\n\nDisclaimer: यह legal advice नहीं है।",
                "variables": ["customer_name", "business_name", "date", "time", "lawyer_name", "service", "order_id"],
                "image_url": None,
            },
            {
                "id": "lawyer_court_reminder",
                "category": TemplateCategory.APPOINTMENT_REMINDER,
                "title": "Court Date Reminder",
                "description": "Reminds about upcoming court date",
                "content": "🏛️ *{{business_name}} - Court Reminder*\n\nनमस्ते {{customer_name}}!\n\nआपका court date है:\n\n📅 {{date}}\n⏰ {{time}}\n🏛️ Court: {{service}}\nCase No: {{case_number}}\n\nकृपया समय पर पहुँचें।",
                "variables": ["customer_name", "business_name", "date", "time", "service", "case_number"],
                "image_url": None,
            },
        ],
    }

    def __init__(self):
        self._templates: Dict[str, MessageTemplate] = {}
        self._build_templates()

    def _build_templates(self):
        for biz_type, tmpl_list in self.PROFESSION_TEMPLATES.items():
            for t in tmpl_list:
                msg_tmpl = MessageTemplate(
                    id=t["id"],
                    business_type=biz_type,
                    category=t["category"],
                    title=t["title"],
                    content=t["content"],
                    variables=t.get("variables", []),
                    language="hi_en",
                    description=t.get("description", ""),
                    image_url=t.get("image_url"),
                )
                self._templates[msg_tmpl.id] = msg_tmpl

    def get_templates_for_business(self, business_type: str) -> List[MessageTemplate]:
        btype = business_type.lower()
        return [t for t in self._templates.values() if t.business_type == btype and t.is_active]

    def get_template(self, template_id: str) -> Optional[MessageTemplate]:
        return self._templates.get(template_id)

    def get_all_business_types(self) -> List[str]:
        return list(self.PROFESSION_TEMPLATES.keys())

    def render(self, template_id: str, variables: Dict[str, Any]) -> str:
        """Render a template by ID with the given variables."""
        tmpl = self._templates.get(template_id)
        if not tmpl:
            return ""
        content = tmpl.content
        for key, value in variables.items():
            content = content.replace("{{" + key + "}}", str(value))
        return content

    def render_by_profession(self, business_type: str, category: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Render a template for a profession + category with variables.

        Returns dict with rendered text and optional image_url.
        """
        btype = business_type.lower()
        cat = category.lower()
        tmpl = None
        for t in self._templates.values():
            if t.business_type == btype and t.category.value == cat:
                tmpl = t
                break
        if not tmpl:
            return {"status": "error", "message": f"No template found for {business_type}/{category}"}

        content = tmpl.content
        for key, value in variables.items():
            content = content.replace("{{" + key + "}}", str(value))

        image_url = tmpl.image_url
        if image_url and "{{" in image_url:
            for key, value in variables.items():
                image_url = image_url.replace("{{" + key + "}}", str(value))

        return {
            "status": "ok",
            "template_id": tmpl.id,
            "category": tmpl.category.value,
            "title": tmpl.title,
            "rendered_text": content,
            "image_url": image_url,
            "variables_used": tmpl.variables,
            "remaining_variables": [
                v for v in tmpl.variables
                if "{{" + v + "}}" in content
            ],
        }

    def render_bulk(self, template_id: str, contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Render a template for multiple contacts with personalization.

        Each contact dict is: {"phone": "+91...", "variables": {...}}
        """
        results = []
        template = self._templates.get(template_id)
        if not template:
            return [{"error": f"Template '{template_id}' not found"} for _ in contacts]

        for contact in contacts:
            variables = dict(contact.get("variables", {}))
            variables.setdefault("business_name", "")
            text = template.content
            for key, value in variables.items():
                text = text.replace("{{" + key + "}}", str(value))

            image_url = template.image_url
            if image_url:
                for key, value in variables.items():
                    image_url = image_url.replace("{{" + key + "}}", str(value))

            results.append({
                "phone": contact.get("phone", ""),
                "rendered_text": text,
                "image_url": image_url,
            })
        return results


template_engine = TemplateEngine()
