"""CA/Accountant Vertical Pack"""


class CAAccountantBot:
    def __init__(self):
        self.name = "CA Assistant"

    def get_response(self, intent: str, message: str, entities: dict, name=None) -> str:
        handlers = {
            "greeting": self._greeting,
            "appointment_booking": self._book_consultation,
            "itr_inquiry": self._itr_inquiry,
            "gst_inquiry": self._gst_inquiry,
            "document_request": self._document,
            "pricing_query": self._pricing,
        }
        fn = handlers.get(intent, self._general)
        return fn(message, entities, name)

    def _greeting(self, msg, entities, name=None):
        n = f" {name} ji" if name else ""
        return (f"Namaste{n}! 👋 Aapka CA assistant yahan hai.\n\n"
                "Main aapki madad kar sakta hoon:\n"
                "📊 ITR filing ke baare mein\n🧾 GST return ke baare mein\n"
                "📄 Document upload karne mein\n📅 CA consultation book karne mein\n\n"
                "Kya main aapki madad kar sakta hoon?")

    def _book_consultation(self, msg, entities, name=None):
        return ("CA consultation book karne ke liye:\n"
                "1️⃣ Kis service chahiye? (ITR filing/GST/Business registration/Other)\n"
                "2️⃣ Aapki preferred date aur time?\n"
                "3️⃣ Aapka naam aur contact?\n\n"
                "Jaise: 'ITR filing ke liye kal 11 baje consultation chahiye'")

    def _itr_inquiry(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "deadline" in msg_l or "last date" in msg_l or "due date" in msg_l or "kab tak" in msg_l:
            return ("ITR filing deadlines:\n"
                    "📅 Individual (no audit): 31 July 2026\n"
                    "📅 Audit cases: 31 October 2026\n"
                    "📅 Revised return: 31 December 2026\n\n"
                    "Kya aap ITR file karwana chahenge? Main aapki madad kar sakta hoon.")
        if "new" in msg_l or "old" in msg_l or "regime" in msg_l or "slab" in msg_l:
            return ("Tax regimes:\n"
                    "🏛️ New Regime (default): Lower rates, no deductions\n"
                    "🏛️ Old Regime: Higher rates, with deductions (80C, 80D, HRA etc.)\n\n"
                    "Kya aap jaanna chahenge ki aapke liye kaunsa better hai?")
        return ("ITR filing ke liye main aapki madad kar sakta hoon.\n"
                "Kya aap bata sakte hain:\n1️⃣ Aapki income source? (Salary/Business/Other)\n"
                "2️⃣ Kya aapke paas Form 16 hai?\n3️⃣ Koi deductions claim karna chahte hain? (80C, 80D, HRA etc.)")

    def _gst_inquiry(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "return" in msg_l:
            return ("GST return filing:\n"
                    "📅 GSTR-1 (Sales): Monthly/Quarterly\n"
                    "📅 GSTR-3B (Summary): 20th of every month\n"
                    "📅 GSTR-9 (Annual): 31 December\n\n"
                    "Kya aap GST return file karwana chahenge?")
        return ("GST ke baare mein jaankari:\n"
                "• GST registration\n• GST return filing (GSTR-1, GSTR-3B, GSTR-9)\n"
                "• Input Tax Credit (ITC) reconciliation\n\n"
                "Kya aap kisi specific GST service ke baare mein jaanna chahte hain?")

    def _document(self, msg, entities, name=None):
        return ("Documents ke liye:\n"
                "1️⃣ Document ki photo/PDF bhej sakte hain\n"
                "2️⃣ Hum CA ko forward kar denge review ke liye\n\n"
                "Acceptable documents:\n📄 Form 16\n📄 Bank statements\n📄 Salary slips\n"
                "📄 Rent receipts\n📄 Investment proofs\n📄 Previous year ITR")

    def _pricing(self, msg, entities, name=None):
        return ("Humari fee structure:\n"
                "📊 ITR Filing: Salary se start hota hai ₹999\n"
                "🧾 GST Return Filing: ₹1,999 per year\n"
                "🏢 Business Registration: Call karke puchhein\n"
                "📋 Audit: Case ke hisaab se\n\n"
                "Exact fees ke liye consultation book karein.")

    def _general(self, msg, entities, name=None):
        return ("Main aapki kaise madad kar sakta hoon?\n"
                "1️⃣ ITR filing / Deadline info\n2️⃣ GST return filing\n"
                "3️⃣ Document upload karein\n4️⃣ CA consultation book karein\n5️⃣ Fee structure\n\n"
                "Kripya option number ya apna message bheje.")