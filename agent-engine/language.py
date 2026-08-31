"""
Multi-language support for the WhatsApp Agent Platform.

Lightweight, dependency-free language detection + response localisation so the
assistant can greet and reply in the user's language. Detection is based on
Unicode script ranges (Devanagari, Tamil, Telugu, Bengali, Kannada, Malayalam,
Gujarati, Gurmukhi) plus a small romanised keyword list for Hinglish.

External machine-translation is intentionally NOT a hard dependency — when an
API key/token is configured the optional `translate()` helper can forward to it,
otherwise the platform falls back to curated templates for the supported
languages.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

# Languages we ship curated templates for.
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
}

DEFAULT_LANGUAGE = "en"

# Unicode script detection ranges (start, end, iso code)
_SCRIPT_RANGES = [
    (0x0900, 0x097F, "hi"),   # Devanagari (Hindi/Marathi)
    (0x0980, 0x09FF, "bn"),   # Bengali
    (0x0A00, 0x0A7F, "pa"),   # Gurmukhi (Punjabi)
    (0x0A80, 0x0AFF, "gu"),   # Gujarati
    (0x0B00, 0x0B7F, "or"),   # Oriya (not templated, detected only)
    (0x0B80, 0x0BFF, "ta"),   # Tamil
    (0x0C00, 0x0C7F, "te"),   # Telugu
    (0x0C80, 0x0CDF, "kn"),   # Kannada
    (0x0D00, 0x0D7F, "ml"),   # Malayalam
]

# Romanised Hinglish / regional cues (lowercased substrings)
_ROMAN_HINTS = {
    "hi": ["namaste", "namaskar", "kaise", "kya", "aap", "hum", "hai", "main", "mera",
           "bhai", "didi", "ji", "karo", "chahiye", "batao"],
    "ta": ["vanakkam", "eppadi", "enna", "ungal", "naan", "sollunga", "ungaluku"],
    "te": ["namaskaram", "ela", "emi", "meeru", "cheppu", "andaru"],
    "bn": ["nomoskar", "kemon", "tumi", "amader", "bole"],
    "mr": ["namaskar", "kasa", "tumhi", "aamhi", "sang", "ahe"],
    "gu": ["namaste", "kem", "tame", "mane", "sangu"],
    "pa": ["sat sri", "kiddan", "tusi", "mainu", "daso"],
    "kn": ["namaskara", "hegidira", "neevu", "heliri"],
    "ml": ["namaskaram", "sugham", "ningal", "parayu"],
}

# Curated fallback templates for the most common intents, per language.
# Keys mirror the orchestrator intent names.
_TEMPLATES: Dict[str, Dict[str, str]] = {
    "en": {
        "greeting": "Hello! 👋 I'm your assistant. How can I help you today?",
        "farewell": "Thank you! 🙏 Let me know if you need anything else.",
        "appointment_booking": "Sure! To book your appointment, please share a date and time.",
        "pricing_query": "For pricing, please let me know which service you're interested in.",
        "support": "I'm happy to help. Could you share a bit more detail?",
        "symptom_check": "Please describe your symptoms. For emergencies call 108!",
        "prescription_request": "Please send a photo of your previous prescription to renew.",
        "lab_report": "You can send a photo/PDF of your lab report.",
        "case_inquiry": "Tell me a little more about your case.",
        "itr_inquiry": "I can help with ITR filing. What is your income source?",
        "menu_inquiry": "We have vegetarian and non-veg options. Anything specific?",
        "document_request": "You can upload the document — just forward the file.",
        "lead_enquiry": "Great! Could you share your name and city?",
        "payment_request": "I can send a payment link. How much is the amount? 💳",
        "human_handoff": "Connecting you with a human agent. Please hold! 🙏",
        "general_query": "Got it. How else can I help you?",
    },
    "hi": {
        "greeting": "Namaste! 👋 Main aapka assistant hoon. Main aapki kaise madad kar sakta hoon?",
        "farewell": "Dhanyavad! 🙏 Koi aur madad chahiye toh bataiye.",
        "appointment_booking": "Ji, appointment book karne ke liye date aur time bataiye.",
        "pricing_query": "Pricing ke liye batayein ki aapko kis service mein interest hai?",
        "support": "Mujhe aapki problem samajhne mein khushi hogi. Thoda detail bataiye.",
        "symptom_check": "Apne symptoms bataayein. Emergency ho toh 108 dial karein!",
        "prescription_request": "Prescription renewal ke liye purani prescription ki photo bheje.",
        "lab_report": "Lab report ki photo/PDF bhej sakte hain.",
        "case_inquiry": "Case ke baare mein thoda aur bataayein?",
        "itr_inquiry": "ITR filing mein main madad kar sakta hoon. Income source kya hai?",
        "menu_inquiry": "Humare paas veg aur non-veg dono hain. Kuch specific dekhein?",
        "document_request": "Document forward kar dein, main dekh lunga.",
        "lead_enquiry": "Bahut achha! Naam aur city bataayein.",
        "payment_request": "Payment link bhej sakta hoon. Kitni amount hai? 💳",
        "human_handoff": "Human agent se connect kar raha hoon. Thoda ruk jaiye! 🙏",
        "general_query": "Samajh gaya. Aur kaise madad karoon?",
    },
    "ta": {
        "greeting": "Vanakkam! 👋 Naan ungal assistant. Ungalukku enna help venum?",
        "farewell": "Nandri! 🙏 Innum venum na solunga.",
        "appointment_booking": "Sure! Appointment book panna oru date and time sollunga.",
        "pricing_query": "Price theriyanum na, enga service venum nu sollunga.",
        "support": "Sure-a help pannuren. Konjam detail sollunga.",
        "symptom_check": "Unga symptoms sollunga. Emergency na 108 ku call pannunga!",
        "prescription_request": "Renew panna munnadi prescription photo anupunga.",
        "lab_report": "Lab report photo/PDF anupalaam.",
        "case_inquiry": "Unga case pathi konjam solunga.",
        "itr_inquiry": "ITR file panna naan help pannuren. Income source enna?",
        "menu_inquiry": "Veg and non-veg irukku. Edhaachum specific?",
        "document_request": "Document forward pannidunga.",
        "lead_enquiry": "Super! Unga name and city sollunga.",
        "payment_request": "Payment link anupuren. Amount evvalo? 💳",
        "human_handoff": "Human agent-ku connect pannuren. Konjam wait pannunga! 🙏",
        "general_query": "Purinjiduchu. Innum enna help?",
    },
    "te": {
        "greeting": "Namaskaram! 👋 Nenu mee assistant. Meeku ela help cheyyagalanu?",
        "farewell": "Dhanyavaadaalu! 🙏 Inka needunte cheppandi.",
        "appointment_booking": "Sure! Appointment book cheyyadaniki oka date and time cheppandi.",
        "pricing_query": "Price teliyali ante, em service kavalo cheppandi.",
        "support": "Help cheyyataniki santhosham. Konchem detail cheppandi.",
        "symptom_check": "Me e symptoms cheppandi. Emergency aithe 108 ki call cheyyandi!",
        "prescription_request": "Renew cheyyadaniki purana prescription photo pampandi.",
        "lab_report": "Lab report photo/PDF pampochu.",
        "case_inquiry": "Me case gurinchi konchem cheppandi.",
        "itr_inquiry": "ITR file cheyyadaniki nenu help cheyyagalanu. Income source emi?",
        "menu_inquiry": "Veg and non-veg unnayi. Emaina specific?",
        "document_request": "Document forward chesi pampandi.",
        "lead_enquiry": "Super! Me name and city cheppandi.",
        "payment_request": "Payment link pampagalanu. Amount entha? 💳",
        "human_handoff": "Human agent ki connect chestunna. Konchem wait cheyyandi! 🙏",
        "general_query": "Ardhamaindi. Inka ela help?",
    },
    "bn": {
        "greeting": "Nomoskar! 👋 Ami apnar assistant. Apnake kibhabe help korte pari?",
        "farewell": "Dhonnobad! 🙏 Aro kichu lagle bolben.",
        "appointment_booking": "Sure! Appointment er jonno ekta date ar time din.",
        "pricing_query": "Price janar jonno bolun kon service e interest.",
        "support": "Help korte khushi. Ektu detail bolun.",
        "symptom_check": "Apnar symptoms bolun. Emergency hole 108 dial korun!",
        "prescription_request": "Renew korar jonno purano prescription er photo pathan.",
        "lab_report": "Lab report er photo/PDF pathan.",
        "case_inquiry": "Apnar case niye ektu bolun.",
        "itr_inquiry": "ITR file e ami help korte pari. Income source ki?",
        "menu_inquiry": "Veg ar non-veg duitoi ache. Kuno specific?",
        "document_request": "Document forward kore pathan.",
        "lead_enquiry": "Bah! Apnar naam ar city bolun.",
        "payment_request": "Payment link pathabo. Amount koto? 💳",
        "human_handoff": "Human agent e connect korchi. Ektu wait korun! 🙏",
        "general_query": "Bujhechi. Aro kibhabe help?",
    },
    "mr": {
        "greeting": "Namaskar! 👋 Mi tumcha assistant. Tumhala kasa madat karu?",
        "farewell": "Dhanyavaad! 🙏 Aani kahi lagnar asel tar sanga.",
        "appointment_booking": "Sure! Appointment book karnyasathi date ani time sanga.",
        "pricing_query": "Price samjavnyasathi konati service aavdatte sanga.",
        "support": "Madat karayala aanandi. Thodi detail sanga.",
        "symptom_check": "Tumchi symptoms sanga. Emergency asel tar 108 la call kara!",
        "prescription_request": "Renew sathi puranchi prescription chi photo pathava.",
        "lab_report": "Lab report chi photo/PDF pathu shakto.",
        "case_inquiry": "Tumcha case thoda sanga.",
        "itr_inquiry": "ITR file madat karu shakto. Income source kaay?",
        "menu_inquiry": "Veg ani non-veg donhi ahet. Kahi specific?",
        "document_request": "Document forward kara.",
        "lead_enquiry": "Chhan! Tumcha naam ani city sanga.",
        "payment_request": "Payment link pathu shakto. Amount kiti? 💳",
        "human_handoff": "Human agent la connect kartoy. Thoda wait kara! 🙏",
        "general_query": "Samajla. Aani kasa madat?",
    },
    "gu": {
        "greeting": "Namaste! 👋 Hu tamaru assistant. Hu tamne kema madad karu?",
        "farewell": "Aabhar! 🙏 Biji kai jarur hoy to baolo.",
        "appointment_booking": "Sure! Appointment book karva date ane time batao.",
        "pricing_query": "Price janva mate batao ke tame kai service ma interest cho?",
        "support": "Madad karava ma anand chhe. Thodi detail batao.",
        "symptom_check": "Tamara symptoms batao. Emergency hoy to 108 par call karo!",
        "prescription_request": "Renew mate purani prescription ni photo mokalo.",
        "lab_report": "Lab report ni photo/PDF mokali shako.",
        "case_inquiry": "Tamaru case vishay thodi vatao.",
        "itr_inquiry": "ITR file ma hu madad karu. Income source shu chhe?",
        "menu_inquiry": "Veg ane non-veg banne chhe. Kai specific?",
        "document_request": "Document forward kari mokalo.",
        "lead_enquiry": "Saru! Tamaru naam ane city batao.",
        "payment_request": "Payment link mokli shaku. Amount ketli? 💳",
        "human_handoff": "Human agent sathe connect karu chhu. Thoda wait raho! 🙏",
        "general_query": "Samajh gaya. Biji kema madad?",
    },
    "kn": {
        "greeting": "Namaskara! 👋 Naanu nimmadu assistant. Nimge hege help madali?",
        "farewell": "Dhanyavaada! 🙏 Innu beku andre heli.",
        "appointment_booking": "Sure! Appointment book madakke oma date and time heli.",
        "pricing_query": "Price gotthe agbekante yav service beku antha heli.",
        "support": "Help maduvadharalli santosha. Thara detail heli.",
        "symptom_check": "Nimmadu symptoms heli. Emergency andre 108 ge call madi!",
        "prescription_request": "Renew madakke hale prescription photo kalsi.",
        "lab_report": "Lab report photo/PDF kalsabahudu.",
        "case_inquiry": "Nimmadu case badhali heli.",
        "itr_inquiry": "ITR file madali andre naanu help madtini. Income source enu?",
        "menu_inquiry": "Veg and non-veg iruvavu. Yenu specific?",
        "document_request": "Document forward madi kalsi.",
        "lead_enquiry": "Channagide! Nimmadu hesaru and city heli.",
        "payment_request": "Payment link kalsabahudu. Amount esthu? 💳",
        "human_handoff": "Human agent ge connect madtiddini. Thara wait madi! 🙏",
        "general_query": "Arthamayitu. Innu hege help?",
    },
    "ml": {
        "greeting": "Namaskaram! 👋 Njan ningalude assistant. Enthu help cheyyan pattum?",
        "farewell": "Nandi! 🙏 Venamel ithare parayuka.",
        "appointment_booking": "Sure! Appointment book cheyyan oru date and time parayuka.",
        "pricing_query": "Price ariyanamengil ethu service aanu interest ennu parayuka.",
        "support": "Help cheyyan santhosham. Kondu detail parayuka.",
        "symptom_check": "Ningalude symptoms parayuka. Emergency aanel 108 il call cheyyuka!",
        "prescription_request": "Renew cheyyan puranda prescription inte photo ayakuka.",
        "lab_report": "Lab report inte photo/PDF ayakam.",
        "case_inquiry": "Ningalude case kurichu kondu parayuka.",
        "itr_inquiry": "ITR file cheyyan njan help cheyyan pattum. Income source enthu?",
        "menu_inquiry": "Veg and non-veg ind. Etho specific?",
        "document_request": "Document forward ayakuka.",
        "lead_enquiry": "Super! Ningalude perum city um parayuka.",
        "payment_request": "Payment link ayakam. Amount ethra? 💳",
        "human_handoff": "Human agent ilek connect cheythu. Kondu wait cheyyuka! 🙏",
        "general_query": "Maniyani. Ini ethra help?",
    },
}


def detect_language(text: str) -> str:
    """Detect the ISO language code of a message.

    Uses Unicode script detection first (authoritative for native scripts),
    then falls back to romanised keyword cues, then English.
    """
    if not text:
        return DEFAULT_LANGUAGE
    # 1. Script-based detection (highest confidence)
    for start, end, code in _SCRIPT_RANGES:
        if any(start <= ord(ch) <= end for ch in text):
            return code
    # 2. Romanised keyword cues
    lowered = text.lower()
    scores: Dict[str, int] = {}
    for lang, hints in _ROMAN_HINTS.items():
        score = sum(1 for h in hints if h in lowered)
        if score:
            scores[lang] = score
    if scores:
        best = max(scores.items(), key=lambda kv: kv[1])
        return best[0]
    return DEFAULT_LANGUAGE


def is_supported(lang: str) -> bool:
    return lang in SUPPORTED_LANGUAGES


def localize(intent: str, lang: str = "en") -> str:
    """Return the localised fallback template for an intent in `lang`."""
    lang = lang if is_supported(lang) else DEFAULT_LANGUAGE
    templates = _TEMPLATES.get(lang, _TEMPLATES[DEFAULT_LANGUAGE])
    return templates.get(intent, templates.get("general_query", ""))


def language_name(lang: str) -> str:
    return SUPPORTED_LANGUAGES.get(lang, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])


def _translate_via_provider(text: str, target: str) -> Optional[str]:
    """Optional machine translation hook. Returns None if unavailable.

    Wired to a configured provider only when explicit credentials exist, so
    the platform never hard-depends on an external translation API.
    """
    token = None
    try:
        from config import settings

        token = getattr(settings, "translation_api_token", None) or getattr(
            settings, "translate_token", None)
    except Exception:
        token = None
    if not token:
        return None
    try:
        import httpx

        resp = httpx.post(
            "https://api.example-translate.in/v1/translate",
            json={"text": text, "target": target},
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json().get("translated_text")
    except Exception:
        return None
    return None


def translate(text: str, target: str) -> str:
    """Translate `text` to `target` language, falling back to original text."""
    if not text or target == DEFAULT_LANGUAGE:
        return text
    out = _translate_via_provider(text, target)
    return out if out else text
