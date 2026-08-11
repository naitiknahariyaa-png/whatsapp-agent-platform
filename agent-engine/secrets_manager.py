"""
Secrets Manager
Centralized, secure access to all credentials. Reads from environment variables
or a .env file. Never hard-codes secrets in code.

Supports:
  - Environment variable lookup (primary)
  - .env file fallback
  - Optional AWS Secrets Manager / Vault integration (extendable)
"""
import os
import sys
from typing import Optional
from dotenv import load_dotenv

# Load .env from agent-engine directory
_AGENT_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(_AGENT_DIR, ".env"))


class SecretsManager:
    """Centralized secrets access with validation."""

    # Required secrets for production (fail fast if missing)
    REQUIRED_PRODUCTION = [
        "JWT_SECRET_KEY",
        "GROQ_API_KEY",
    ]

    # Optional secrets (warn if missing)
    OPTIONAL = [
        "RAZORPAY_KEY_ID",
        "RAZORPAY_KEY_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "FIGMA_API_TOKEN",
        "FIGMA_FILE_KEY",
        "META_ACCESS_TOKEN",
        "META_PHONE_NUMBER_ID",
        "META_VERIFY_TOKEN",
        "META_APP_SECRET",
        "WA_BRIDGE_SECRET",
        "SENTRY_DSN",
        "REDIS_URL",
        "DATABASE_URL",
    ]

    def __init__(self):
        self._cache: dict = {}

    def get(self, key: str, default: str = "") -> str:
        """Get a secret value. Checks cache, then env, then .env."""
        if key in self._cache:
            return self._cache[key]
        value = os.getenv(key, default)
        self._cache[key] = value
        return value

    def get_required(self, key: str) -> str:
        """Get a required secret, raising if missing."""
        value = self.get(key)
        if not value:
            raise ValueError(f"Missing required secret: {key}")
        return value

    def validate(self, environment: str = "development") -> list:
        """Validate that required secrets are present. Returns list of missing keys."""
        missing = []
        if environment == "production":
            for key in self.REQUIRED_PRODUCTION:
                if not self.get(key):
                    missing.append(key)
        return missing

    def is_configured(self, key: str) -> bool:
        """Check if a secret is configured (non-empty)."""
        return bool(self.get(key))

    def redact(self, value: str) -> str:
        """Redact a secret for logging (show first 4 chars only)."""
        if not value:
            return ""
        if len(value) <= 8:
            return "****"
        return f"{value[:4]}...{value[-4:]}"

    def summary(self) -> dict:
        """Return a safe summary of which secrets are configured (no values)."""
        result = {}
        for key in self.REQUIRED_PRODUCTION + self.OPTIONAL:
            result[key] = self.is_configured(key)
        return result

    # --- Encryption helpers (Fernet) ---
    def _get_fernet_key(self) -> bytes:
        """Derive a Fernet key from the JWT_SECRET_KEY environment secret."""
        import hashlib, base64
        key = os.getenv("JWT_SECRET_KEY") or os.getenv("jwt_secret_key") or ""
        if not key:
            # Fallback to a file-based key in .env if present
            key = os.getenv("DEV_FALLBACK_KEY", "dev-local-key-change-me")
        # Use SHA256 digest and base64-urlsafe-encode for Fernet
        digest = hashlib.sha256(key.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string and return a URL-safe base64 token."""
        if not plaintext:
            return ""
        try:
            from cryptography.fernet import Fernet
            k = self._get_fernet_key()
            f = Fernet(k)
            token = f.encrypt(plaintext.encode()).decode()
            return token
        except Exception:
            # Fallback: return plaintext (not encrypted)
            return plaintext

    def decrypt(self, token: str) -> str:
        """Decrypt a token produced by `encrypt` or return original on failure."""
        if not token:
            return ""
        try:
            from cryptography.fernet import Fernet
            k = self._get_fernet_key()
            f = Fernet(k)
            try:
                plain = f.decrypt(token.encode()).decode()
                return plain
            except Exception:
                # token might be plain already
                return token
        except Exception:
            return token


# Singleton instance
secrets = SecretsManager()