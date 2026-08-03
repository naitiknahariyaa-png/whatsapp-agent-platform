"""MBA/Education Vertical Pack - Business & Management Consulting"""


class MBABot:
    def __init__(self):
        self.name = "MBA Admissions Assistant"

    def get_response(self, intent: str, message: str, entities: dict, name=None) -> str:
        handlers = {
            "greeting": self._greeting,
            "appointment_booking": self._book_consultation,
            "pricing_query": self._fees,
            "document_request": self._documents,
            "lead_enquiry": self._admission_flow,
            "menu_inquiry": self._programs,
            "case_inquiry": self._career_counseling,
        }
        fn = handlers.get(intent, self._general)
        return fn(message, entities, name)

    def _greeting(self, msg, entities, name=None):
        n = f" {name} ji" if name else ""
        return (f"Namaste{n}! 👋 Aapka MBA admissions assistant yahan hai.\n\n"
                "Main aapki madad kar sakta hoon:\n"
                "🎓 MBA programs ke baare mein\n📝 Admission process mein\n"
                "💰 Fees & scholarships mein\n🧭 Career counseling mein\n"
                "📄 Document upload karne mein\n\n"
                "Kya main aapki madad kar sakta hoon?")

    def _programs(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "finance" in msg_l:
            return ("Finance specialization mein:\n"
                    "📊 Investment Banking\n💰 Corporate Finance\n"
                    "📈 Financial Analysis\n🏦 Banking & Insurance\n\n"
                    "Kya aap finance ke baare mein aur jaanna chahenge?")
        if "marketing" in msg_l:
            return ("Marketing specialization mein:\n"
                    "📣 Digital Marketing\n🛍️ Brand Management\n"
                    "📊 Market Research\n🌐 Social Media Strategy\n\n"
                    "Kya aap marketing ke baare mein aur jaanna chahenge?")
        if "hr" in msg_l or "human resource" in msg_l:
            return ("HR specialization mein:\n"
                    "👥 Talent Acquisition\n📋 HR Analytics\n"
                    "🏢 Organizational Development\n⚖️ Labour Law\n\n"
                    "Kya aap HR ke baare mein aur jaanna chahenge?")
        if "operation" in msg_l:
            return ("Operations specialization mein:\n"
                    "🏭 Supply Chain Management\n📦 Logistics\n"
                    "⚙️ Process Optimization\n📊 Project Management\n\n"
                    "Kya aap operations ke baare mein aur jaanna chahenge?")
        return ("Humare MBA programs:\n"
                "🎓 MBA (General)\n📊 MBA Finance\n📣 MBA Marketing\n"
                "👥 MBA HR\n🏭 MBA Operations\n\n"
                "Kis specialization mein interest hai?")

    def _admission_flow(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "cat" in msg_l or "gmat" in msg_l or "entrance" in msg_l:
            return ("Admission process:\n"
                    "1️⃣ Entrance exam: CAT/GMAT/MAT (score required)\n"
                    "2️⃣ Application form + SOP\n"
                    "3️⃣ Group Discussion + Personal Interview\n"
                    "4️⃣ Final selection + Fee payment\n\n"
                    "Kya aapko entrance exam ke baare mein jaankari chahiye?")
        if "eligib" in msg_l or "qualif" in msg_l:
            return ("Eligibility criteria:\n"
                    "🎓 Bachelor's degree (any stream)\n"
                    "📊 Minimum 50% marks (45% for reserved)\n"
                    "📝 Valid CAT/GMAT/MAT score\n"
                    "💼 Work experience (preferred, not mandatory)\n\n"
                    "Kya aap apni eligibility check karna chahenge?")
        return ("Admission ke liye:\n"
                "1️⃣ Entrance exam score (CAT/GMAT/MAT)\n"
                "2️⃣ Application form bharne mein help\n"
                "3️⃣ SOP (Statement of Purpose) guidance\n"
                "4️⃣ Interview preparation\n\n"
                "Kis step mein help chahiye?")

    def _fees(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "scholar" in msg_l or "loan" in msg_l or "emi" in msg_l:
            return ("Fee assistance options:\n"
                    "🎓 Merit scholarships (up to 100%)\n"
                    "🏦 Education loans (all major banks)\n"
                    "💳 EMI options (6-36 months)\n"
                    "👨‍👩‍👧 Need-based financial aid\n\n"
                    "Kya aap scholarship eligibility check karna chahenge?")
        return ("MBA program fees:\n"
                "🎓 Full-time MBA: ₹8-15 Lakhs (2 years)\n"
                "📊 Executive MBA: ₹5-10 Lakhs (1 year)\n"
                "🌐 Online MBA: ₹2-5 Lakhs\n\n"
                "Exact fees program aur college par depend karti hai. Kya aap kisi specific program ke baare mein jaanna chahenge?")

    def _documents(self, msg, entities, name=None):
        return ("Admission ke liye documents:\n"
                "1️⃣ 10th & 12th marksheets\n"
                "2️⃣ Graduation degree + marksheets\n"
                "3️⃣ Entrance exam scorecard (CAT/GMAT/MAT)\n"
                "4️⃣ Work experience certificate (if any)\n"
                "5️⃣ SOP + LORs\n"
                "6️⃣ Passport size photo + ID proof\n\n"
                "Aap documents ki photo/PDF bhej sakte hain, hum check karke batayenge.")

    def _career_counseling(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "finance" in msg_l or "bank" in msg_l:
            return ("Finance career paths:\n"
                    "🏦 Investment Banker\n💰 Financial Analyst\n"
                    "📊 Portfolio Manager\n🏢 Corporate Finance\n\n"
                    "Finance mein strong analytical skills aur numbers ki samajh chahiye.")
        if "marketing" in msg_l or "brand" in msg_l:
            return ("Marketing career paths:\n"
                    "📣 Brand Manager\n🛍️ Digital Marketing Head\n"
                    "📊 Market Research Analyst\n🌐 Growth Hacker\n\n"
                    "Marketing mein creativity aur communication skills important hain.")
        if "hr" in msg_l:
            return ("HR career paths:\n"
                    "👥 HR Manager\n📋 Talent Acquisition Lead\n"
                    "🏢 HR Business Partner\n⚖️ Compensation Analyst\n\n"
                    "HR mein people skills aur empathy important hain.")
        return ("Career counseling ke liye:\n"
                "1️⃣ Aapki graduation stream kya hai?\n"
                "2️⃣ Aapki strengths kya hain? (numbers/creativity/people)\n"
                "3️⃣ Kya aapko work experience hai?\n\n"
                "In answers ke basis par main aapko best specialization suggest karunga.")

    def _book_consultation(self, msg, entities, name=None):
        return ("Career counselor consultation book karne ke liye:\n"
                "1️⃣ Kis baare mein consultation chahiye? (admission/career/fees)\n"
                "2️⃣ Aapki preferred date aur time?\n"
                "3️⃣ Aapka naam aur contact?\n\n"
                "Jaise: 'Admission ke liye kal 3 baje consultation chahiye'")

    def _general(self, msg, entities, name=None):
        return ("Main aapki kaise madad kar sakta hoon?\n"
                "1️⃣ MBA programs dekhne\n2️⃣ Admission process\n"
                "3️⃣ Fees & scholarships\n4️⃣ Career counseling\n"
                "5️⃣ Document upload\n\n"
                "Kripya option number ya apna message bheje.")