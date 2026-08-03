"""Doctor/Clinic Vertical Pack"""


class DoctorClinicBot:
    def __init__(self):
        self.name = "Doctor Assistant"

    def get_response(self, intent: str, message: str, entities: dict, name=None) -> str:
        handlers = {
            "greeting": self._greeting,
            "appointment_booking": self._book_appointment,
            "symptom_check": self._symptom_check,
            "prescription_request": self._prescription,
            "lab_report": self._lab_report,
            "pricing_query": self._pricing,
        }
        fn = handlers.get(intent, self._general)
        return fn(message, entities, name)

    def _greeting(self, msg, entities, name=None):
        n = f" Dr. {name}" if name else ""
        return (f"Namaste! 👋 Dr.{n} ke clinic mein aapka swagat hai.\n\nMain aapki madad kar sakta hoon:\n"
                "🩺 Appointment book karne mein\n🏥 Symptoms check karne mein\n💊 Prescription renewal mein\n"
                "📋 Lab reports ke baare mein\n\nKya aap bata sakte hain?")

    def _book_appointment(self, msg, entities, name=None):
        date = entities.get("date", "nahi bataya")
        time = entities.get("time", "nahi bataya")
        if date == "nahi bataya" and time == "nahi bataya":
            return ("Ji, appointment book karne ke liye:\n1️⃣ Kaunsi date?\n2️⃣ Kis time?\n"
                    "3️⃣ Kya problem hai? (symptoms)\n4️⃣ Kisi specific doctor se milna hai?\n\nJaise: 'Kal 3 baje Dr. Sharma se milna hai'")
        return (f"Aapne bataya: Date - {date}, Time - {time}\n\nMain availability check kar raha hoon...\n"
                "Kya aap apna naam aur symptoms bata sakte hain?")

    def _symptom_check(self, msg, entities, name=None):
        symptoms = []
        smap = {"fever": "बुखार", "cough": "खांसी", "cold": "सर्दी", "headache": "सिरदर्द",
                "stomach": "पेट दर्द", "vomiting": "उल्टी", "body pain": "शरीर दर्द",
                "throat": "गले में दर्द", "chest pain": "सीने में दर्द", "breathing": "सांस की दिक्कत",
                "skin": "त्वचा की समस्या", "eye": "आँख की समस्या"}
        for kw, display in smap.items():
            if kw in msg.lower():
                symptoms.append(display)
        if symptoms:
            return (f"Aapne bataye symptoms: {', '.join(symptoms)}\n\n📋 Note: Main AI assistant hoon, doctor nahi.\n"
                    "Kya aap doctor se appointment book karna chahenge?")
        return ("Kya aap apne symptoms detail mein bata sakte hain?\n\n⚠️ Emergency hai toh 108 dial karein!")

    def _prescription(self, msg, entities, name=None):
        return ("Prescription renewal ke liye:\n1️⃣ Purani prescription ki photo bheje\n2️⃣ Ya prescription number bataye\n\n"
                "Doctor se approval ke baad e-prescription bhej denge.")

    def _lab_report(self, msg, entities, name=None):
        return ("Lab reports ke liye:\n1️⃣ Report ki photo/PDF bhej sakte hain\n2️⃣ Hum doctor ko forward kar denge\n\n"
                "Ya aap naye test book karwana chahte hain?")

    def _pricing(self, msg, entities, name=None):
        return ("Humari clinic ke charges:\n🩺 General Consultation: Call karke puchhein\n"
                "💊 Medicine: Prescription ke hisaab se\n🧪 Lab Tests: Package ke hisaab se\n\n"
                "Details ke liye clinic par call karein.")

    def _general(self, msg, entities, name=None):
        return ("Main aapki kaise madad kar sakta hoon?\n1️⃣ नया appointment बुक करें\n"
                "2️⃣ अपॉइंटमेंट रीशेड्यूल करें\n3️⃣ Prescription renewal\n4️⃣ Lab reports\n"
                "5️⃣ Clinic की जानकारी\n\nKripya option number ya apna message bheje.")