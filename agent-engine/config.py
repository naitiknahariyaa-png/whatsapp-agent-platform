import os
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

    groq_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_provider: str = "groq"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    database_url: str = "sqlite+aiosqlite:///./wap_data.db"
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "whatsapp_agent"
    redis_url: str = "redis://localhost:6379/0"
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    whatsapp_bridge_url: str = "http://127.0.0.1:3001"
    broadcast_rate_per_sec: float = 1.0
    agent_api_url: str = "http://127.0.0.1:8000"
    wa_bridge_secret: str = ""
    meta_access_token: str = ""
    meta_phone_number_id: str = ""
    meta_verify_token: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    telegram_bot_token: str = ""
    figma_api_token: str = ""
    figma_file_key: str = ""
    jwt_secret_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "no-reply@whatsapp-agent.local"
    smtp_use_tls: bool = True
    otp_expiry_minutes: int = 15
    email_verification_expiry_hours: int = 24
    password_reset_expiry_hours: int = 1
    frontend_url: str = "http://localhost:8000"
    host: str = "0.0.0.0"
    port: int = 8000
    flipkart_client_id: str = ""
    flipkart_client_secret: str = ""
    flipkart_api_url: str = "https://api.flipkart.net"
    amazon_client_id: str = ""
    amazon_client_secret: str = ""
    amazon_refresh_token: str = ""
    amazon_sp_api_url: str = "https://sellingpartnerapi-na.amazon.com"


settings = Settings()
# Build DATABASE_URL from PostgreSQL components if not explicitly set to SQLite
if settings.database_url.startswith("sqlite"):
    if settings.postgres_user and settings.postgres_password and settings.postgres_host:
        settings.database_url = (
            f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
            f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
        )
# Also load into os.environ so other modules can access via os.getenv
os.environ.setdefault("GROQ_API_KEY", settings.groq_api_key)
os.environ.setdefault("LLM_PROVIDER", settings.llm_provider)
os.environ.setdefault("LLM_MODEL", settings.llm_model)
os.environ.setdefault("DATABASE_URL", settings.database_url)
os.environ.setdefault("WA_BRIDGE_SECRET", settings.wa_bridge_secret)
os.environ.setdefault("WHATSAPP_BRIDGE_URL", settings.whatsapp_bridge_url)
os.environ.setdefault("AGENT_API_URL", settings.agent_api_url)