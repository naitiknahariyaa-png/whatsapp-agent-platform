from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.messages import AIMessage
from config import settings


def get_llm() -> BaseChatModel:
    provider = settings.llm_provider.lower()
    if provider == "groq":
        if not settings.groq_api_key or settings.groq_api_key == "your_groq_api_key_here":
            print("[!] No Groq API key. Using Mock LLM for testing.")
            return MockLLM()
        return ChatGroq(model=settings.llm_model, temperature=0.3, max_tokens=200,
                        groq_api_key=settings.groq_api_key)
    elif provider == "ollama":
        return ChatOllama(model=settings.llm_model, base_url=settings.ollama_base_url,
                          temperature=0.3, num_predict=200)
    print(f"[!] Unknown provider: {provider}. Using Mock LLM.")
    return MockLLM()


class MockLLM(BaseChatModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1].content if messages else ""
        
        # Extract actual user message - look for "User message:" line (last occurrence)
        user_msg = ""
        lines = last.strip().split('\n')
        for line in reversed(lines):
            if line.strip().startswith("User message:"):
                user_msg = line.split("User message:", 1)[1].strip()
                break
        if not user_msg:
            # Fallback: use last non-empty line that's not a prompt instruction
            lines = [l.strip() for l in lines if l.strip()]
            for line in reversed(lines):
                # Skip prompt instructions and examples
                if not any(line.startswith(p) for p in ["-", "Return", "JSON", "Previous", "User's", "Generate", "You are", "Keep it"]):
                    user_msg = line
                    break
            if not user_msg and lines:
                user_msg = lines[-1]
        
        msg = user_msg.lower()
        
        # Greeting
        if any(w in msg for w in ["hello", "hi", "hey", "namaste", "namaskar", "good morning", "good evening"]):
            resp = "Namaste! 👋 Main aapka AI assistant hoon. Main aapki kaise madad kar sakta hoon?"
        # Farewell
        elif any(w in msg for w in ["bye", "goodbye", "alvida", "dhanyavad", "thank", "shukriya", "phir milenge"]):
            resp = "Dhanyavad! 🙏 Koi aur madad chahiye toh bataiye. Shubh din!"
        # Appointment
        elif any(w in msg for w in ["appointment", "book", "schedule", "meeting", "slot", "visit", "table"]):
            resp = "Ji, appointment book karne ke liye kya aap date aur time bata sakte hain?"
        # Pricing
        elif any(w in msg for w in ["price", "cost", "rate", "kitna", "charges", "fees", "fee", "pricing"]):
            resp = "Pricing ke baare mein jaankari ke liye, kya aap bata sakte hain ki aapko kis service mein interest hai?"
        # Support
        elif any(w in msg for w in ["help", "support", "problem", "issue", "error", "not working"]):
            resp = "Mujhe aapki problem samajhne mein khushi hogi. Kya aap thoda detail mein bata sakte hain?"
        # Symptoms (Doctor)
        elif any(w in msg for w in ["fever", "cough", "cold", "headache", "pain", "bukhar", "khansi", "sardi", "dard"]):
            resp = "Kya aap apne symptoms detail mein bata sakte hain? Emergency hai toh 108 dial karein!"
        # Prescription
        elif any(w in msg for w in ["prescription", "dawai", "medicine"]):
            resp = "Prescription renewal ke liye purani prescription ki photo bheje."
        # Lab report
        elif any(w in msg for w in ["lab", "report", "test", "blood"]):
            resp = "Lab reports ke liye report ki photo/PDF bhej sakte hain."
        # Legal case
        elif any(w in msg for w in ["case", "court", "legal", "mukadma", "property dispute", "divorce", "criminal"]):
            resp = "Kya aap case ke baare mein thoda aur bata sakte hain? Jaise: criminal, civil, property, family, etc."
        # ITR/Tax
        elif any(w in msg for w in ["itr", "tax", "gst", "income tax", "return filing", "deadline"]):
            resp = "ITR filing ke liye main aapki madad kar sakta hoon. Kya aap bata sakte hain ki aapki income source kya hai?"
        # Menu
        elif any(w in msg for w in ["menu", "food", "khana", "order", "delivery"]):
            resp = "Humare menu mein veg aur non-veg dono options hain. Kya aap kuch specific dekhna chahenge?"
        # Document
        elif any(w in msg for w in ["document", "upload", "file", "pdf", "photo", "image"]):
            resp = "Ji, aap document upload kar sakte hain. Bas file forward karein, main automatically process kar lunga!"
        # Lead enquiry
        elif any(w in msg for w in ["interested", "buy", "purchase", "subscribe", "chahiye", "lagna"]):
            resp = "Bahut achha! Aap humari services mein interest dikha rahe hain. Kya aap apna naam aur city bata sakte hain?"
        # General
        else:
            resp = f"Main samajh gaya. Aapne kaha: '{last}'. Main aapki kaise madad kar sakta hoon?"
        
        message = AIMessage(content=resp)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "mock"
