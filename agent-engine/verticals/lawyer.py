"""Lawyer/Legal Vertical Pack"""


class LawyerBot:
    def __init__(self):
        self.name = "Legal Assistant"

    def get_response(self, intent: str, message: str, entities: dict, name=None) -> str:
        handlers = {
            "greeting": self._greeting,
            "appointment_booking": self._book_consultation,
            "case_inquiry": self._case_inquiry,
            "document_request": self._document,
            "pricing_query": self._pricing,
        }
        fn = handlers.get(intent, self._general)
        return fn(message, entities, name)

    def _greeting(self, msg, entities, name=None):
        n = f" {name} ji" if name else ""
        return (f"Namaste{n}! 👋 Aapka legal assistant yahan hai.\n\n"
                "Main aapki madad kar sakta hoon:\n"
                "⚖️ Case consultation book karne mein\n📄 Legal documents ke baare mein\n"
                "💰 Fee structure jaankari lene mein\n❓ Aapke legal sawaalo ke jawab dene mein\n\n"
                "⚠️ Disclaimer: Main AI hoon, lawyer nahi. Legal advice ke liye lawyer se milein.\n\n"
                "Kya main aapki madad kar sakta hoon?")

    def _book_consultation(self, msg, entities, name=None):
        return ("Ji, consultation book karne ke liye:\n"
                "1️⃣ Kis type ka case hai? (criminal/civil/family/property/other)\n"
                "2️⃣ Aapki preferred date aur time?\n"
                "3️⃣ Aapka naam aur contact?\n\n"
                "Jaise: 'Property dispute ke liye kal 2 baje consultation chahiye'")

    def _case_inquiry(self, msg, entities, name=None):
        msg_l = msg.lower()
        case_types = {"criminal": "आपराधिक मामला", "civil": "सिविल मामला", "property": "संपत्ति विवाद",
                      "family": "पारिवारिक मामला", "divorce": "तलाक", "cheque bounce": "चेक बाउंस",
                      "consumer": "उपभोक्ता मामला", "employment": "रोजगार मामला"}
        found = [v for k, v in case_types.items() if k in msg_l]
        if found:
            return (f"Aapne bataya: {', '.join(found)}\n\n"
                    "Is case ke liye humare specialist lawyers hain. Kya aap consultation book karna chahenge?\n"
                    "Ya koi specific sawaal hai?")
        return ("Kya aap case ke baare mein thoda aur bata sakte hain?\n"
                "Jaise: criminal, civil, property, family, divorce, cheque bounce, consumer case, etc.")

    def _document(self, msg, entities, name=None):
        return ("Legal documents ke liye:\n"
                "1️⃣ Document ki photo/PDF bhej sakte hain\n"
                "2️⃣ Hum lawyer ko review ke liye forward karenge\n"
                "3️⃣ Lawyer aapko document ke baare mein batayenge\n\n"
                "Ya aap naye document banwana chahte hain? (jaise: agreement, affidavit, will)")

    def _pricing(self, msg, entities, name=None):
        return ("Humari legal fee structure:\n"
                "⚖️ Initial Consultation: Call karke puchhein\n"
                "📄 Document Drafting: Case ke hisaab se\n"
                "🏛️ Court Representation: Case type par depend karta hai\n\n"
                "Exact fees ke liye consultation book karein.")

    def _general(self, msg, entities, name=None):
        return ("Main aapki kaise madad kar sakta hoon?\n"
                "1️⃣ नया consultation बुक करें\n"
                "2️⃣ Case ke baare mein jaankari\n"
                "3️⃣ Legal document upload karein\n"
                "4️⃣ Fee structure\n\n"
                "⚠️ Disclaimer: Main AI hoon. Legal advice ke liye lawyer se milein.")