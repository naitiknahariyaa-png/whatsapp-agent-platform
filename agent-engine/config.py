import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_provider: str = "groq"
    ollama_base_url: str = "http://localhost:11434"
    database_url: str = "sqlite+aiosqlite:///./wap_data.db"
    redis_url: str = "redis://localhost:6379/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    whatsapp_bridge_url: str = "http://localhost:3001"
    broadcast_rate_per_sec: float = 1.0
    agent_api_url: str = "http://localhost:8000"
    wa_bridge_secret: str = ""
    # Meta WhatsApp Cloud API (official)
    meta_access_token: str = ""
    meta_phone_number_id: str = ""
    meta_verify_token: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    telegram_bot_token: str = ""
    figma_api_token: str = ""
    figma_file_key: str = ""
    jwt_secret_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


settings = Settings()
# Also load into os.environ so other modules can access via os.getenv
os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
os.environ.setdefault("LLM_PROVIDER", settings.llm_provider)
os.environ.setdefault("LLM_MODEL", settings.llm_model)
os.environ.setdefault("DATABASE_URL", settings.database_url)
os.environ.setdefault("WA_BRIDGE_SECRET", settings.wa_bridge_secret)
os.environ.setdefault("WHATSAPP_BRIDGE_URL", settings.whatsapp_bridge_url)
os.environ.setdefault("AGENT_API_URL", settings.agent_api_url)