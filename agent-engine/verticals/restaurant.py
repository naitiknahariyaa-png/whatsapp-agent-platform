"""Restaurant Vertical Pack"""


class RestaurantBot:
    def __init__(self):
        self.name = "Restaurant Assistant"

    def get_response(self, intent: str, message: str, entities: dict, name=None) -> str:
        handlers = {
            "greeting": self._greeting,
            "appointment_booking": self._table_booking,
            "menu_inquiry": self._menu_inquiry,
            "order_status": self._order_status,
            "pricing_query": self._pricing,
        }
        fn = handlers.get(intent, self._general)
        return fn(message, entities, name)

    def _greeting(self, msg, entities, name=None):
        n = f" {name} ji" if name else ""
        return (f"Namaste{n}! 👋 Aapke restaurant mein aapka swagat hai.\n\n"
                "Main aapki madad kar sakta hoon:\n"
                "🍽️ Table book karne mein\n📋 Menu dekhne mein\n"
                "🛵 Order status check karne mein\n🎉 Party booking karne mein\n\n"
                "Kya main aapki madad kar sakta hoon?")

    def _table_booking(self, msg, entities, name=None):
        date = entities.get("date", "nahi bataya")
        time = entities.get("time", "nahi bataya")
        if date == "nahi bataya" and time == "nahi bataya":
            return ("Table book karne ke liye:\n"
                    "1️⃣ Kitne log? (2/4/6/8)\n2️⃣ Kaunsi date?\n3️⃣ Kis time?\n"
                    "4️⃣ Koi special occasion? (Birthday/Anniversary/Other)\n\n"
                    "Jaise: 'Kal raat 8 baje 4 log ke liye table chahiye'")
        return (f"Aapne bataya: {date} ko {time} par\n\n"
                "Kitne log ke liye booking chahiye? Main availability check kar raha hoon.")

    def _menu_inquiry(self, msg, entities, name=None):
        msg_l = msg.lower()
        if "veg" in msg_l or "vegetarian" in msg_l or "shakahari" in msg_l:
            return ("Humare veg options:\n🥗 Starters: Paneer tikka, Veg spring roll\n"
                    "🍛 Main Course: Dal makhani, Paneer butter masala, Veg biryani\n"
                    "🍚 Rice/Bread: Jeera rice, Naan, Roti\n"
                    "🍨 Dessert: Gulab jamun, Ice cream\n\n"
                    "Kya aap kisi specific dish ke baare mein jaanna chahenge?")
        if "non veg" in msg_l or "chicken" in msg_l or "mutton" in msg_l or "fish" in msg_l:
            return ("Humare non-veg options:\n🍗 Starters: Chicken tikka, Fish fry\n"
                    "🍛 Main Course: Butter chicken, Chicken biryani, Mutton curry\n"
                    "🍚 Rice/Bread: Biryani, Naan, Roti\n\n"
                    "Kya aap kisi specific dish ke baare mein jaanna chahenge?")
        return ("Humare menu mein:\n🥗 Starters\n🍛 Main Course (Veg & Non-Veg)\n"
                "🍚 Rice & Breads\n🍨 Desserts\n🥤 Beverages\n\n"
                "Kya aap veg ya non-veg menu dekhna chahenge?")

    def _order_status(self, msg, entities, name=None):
        return ("Order status check karne ke liye:\n"
                "1️⃣ Aapka order number kya hai?\n2️⃣ Ya aapka phone number batayein\n\n"
                "Main aapko current status bata dunga.")

    def _pricing(self, msg, entities, name=None):
        return ("Humari pricing range:\n"
                "🍽️ Starters: ₹150 - ₹350\n🍛 Main Course: ₹250 - ₹600\n"
                "🍚 Rice/Bread: ₹80 - ₹200\n🍨 Desserts: ₹100 - ₹250\n"
                "🥤 Beverages: ₹50 - ₹200\n\n"
                "Exact prices ke liye menu dekhne ka option select karein.")

    def _general(self, msg, entities, name=None):
        return ("Main aapki kaise madad kar sakta hoon?\n"
                "1️⃣ Table book karein\n2️⃣ Menu dekhein\n"
                "3️⃣ Order status check karein\n4️⃣ Party/Event booking\n5️⃣ Restaurant ki jaankari\n\n"
                "Kripya option number ya apna message bheje.")