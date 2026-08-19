"""
Email Authentication Service — OTP login, email verification, password reset.

Provides:
  - EmailService: SMTP email sending with console-fallback for dev mode
  - EmailAuthService: orchestrates OTP generation, token verification,
    email verification, and password-reset flows with DB persistence
  - email_auth_service: singleton instance used by main.py routes

Security:
  - All tokens / OTP codes are SHA-256-hashed before storage (never plaintext)
  - OTP codes are 6-digit numeric, 15-min expiry by default
  - Verification / reset tokens are 256-bit cryptographically random
  - Tokens are single-use and invalidated once consumed
  - Rate limiting on OTP requests to prevent abuse
"""
import os
import ssl
import smtplib
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any, Tuple, List

from sqlalchemy import select, delete, and_

from db import async_session
from config import settings
from logging_setup import get_logger

logger = get_logger("email_auth")

# ---------------------------------------------------------------------------
# Constants (overridable via env)
# ---------------------------------------------------------------------------

OTP_LENGTH = int(os.getenv("OTP_LENGTH", "6"))
OTP_EXPIRY_MINUTES = int(getattr(settings, "otp_expiry_minutes", 15) or 15)
VERIFICATION_TOKEN_EXPIRY_HOURS = int(
    getattr(settings, "email_verification_expiry_hours", 24) or 24
)
PASSWORD_RESET_EXPIRY_HOURS = int(
    getattr(settings, "password_reset_expiry_hours", 1) or 1
)
BASE_URL = os.getenv("FRONTEND_URL", getattr(settings, "frontend_url", "http://localhost:8000"))

# In-memory rate-limit buckets for OTP requests (per email, per minute)
_otp_rate_buckets: Dict[str, List[float]] = {}
_OTP_RATE_MAX_PER_MIN = 3  # max 3 OTP requests per email per minute


def _hash_value(value: str) -> str:
    """SHA-256 hash a token or OTP before storage/comparison."""
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Email Service
# ---------------------------------------------------------------------------

class EmailService:
    """
    Send emails via SMTP. Falls back to console logging when SMTP is
    not configured (development mode).
    """

    def __init__(self):
        self.smtp_host = settings.smtp_host or os.getenv("SMTP_HOST", "")
        self.smtp_port = int(settings.smtp_port or os.getenv("SMTP_PORT", "587"))
        self.smtp_username = settings.smtp_username or os.getenv("SMTP_USERNAME", "")
        self.smtp_password = settings.smtp_password or os.getenv("SMTP_PASSWORD", "")
        self.smtp_from_email = (
            settings.smtp_from_email
            or os.getenv("SMTP_FROM_EMAIL", "no-reply@whatsapp-agent.local")
        )
        self.smtp_use_tls = str(
            settings.smtp_use_tls or os.getenv("SMTP_USE_TLS", "true")
        ).lower() in ("true", "1", "yes", "on")
        self.enabled = bool(self.smtp_host)

    # -- public API ----------------------------------------------------------

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str = "",
    ) -> Tuple[bool, str]:
        """
        Send an email. Returns (success, message).

        When SMTP is not configured, logs the email to the console instead
        so the flow is fully testable in development without an SMTP server.
        """
        if not self.enabled:
            logger.info(f"[EMAIL-DEV] To: {to_email} | Subject: {subject}")
            logger.info(f"[EMAIL-DEV] Body (text): {text_content[:300]}")
            logger.info(f"[EMAIL-DEV] Body (html): {html_content[:300]}")
            return True, f"Email logged to console (SMTP not configured). To: {to_email}"

        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = self.smtp_from_email
            msg["To"] = to_email
            msg["Subject"] = subject

            if text_content:
                msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            context = ssl.create_default_context()

            if self.smtp_use_tls:
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
                server.starttls(context=context)
            else:
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30, context=context)

            if self.smtp_username and self.smtp_password:
                server.login(self.smtp_username, self.smtp_password)

            server.sendmail(self.smtp_from_email, to_email, msg.as_string())
            server.quit()

            logger.info(f"[v] Email sent to {to_email}: {subject}")
            return True, "Email sent successfully"
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False, str(e)

    # -- email templates -----------------------------------------------------

    def _brand(self) -> str:
        return "WhatsApp Agent Platform"

    def render_verification_email(self, token: str, full_name: str = "") -> Tuple[str, str, str]:
        """Return (subject, html, text) for the email-verification link."""
        brand = self._brand()
        verify_url = f"{BASE_URL}/auth/verify-email/{token}"
        subject = f"✓ Verify your email — {brand}"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body {{ font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px; }}
.card {{ max-width: 480px; margin: 0 auto; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
h1 {{ color: #25D366; margin-top: 0; }}
.btn {{ display: inline-block; background: #25D366; color: white; text-decoration: none; padding: 12px 28px; border-radius: 8px; font-weight: bold; margin: 16px 0; }}
.code {{ font-family: monospace; background: #f0f0f0; padding: 8px 12px; border-radius: 4px; font-size: 14px; word-break: break-all; }}
.small {{ color: #888; font-size: 12px; margin-top: 24px; }}
</style></head><body>
<div class="card">
<h1>Verify your email</h1>
<p>Hi{(' ' + full_name) if full_name else ''},</p>
<p>Welcome to {brand}! Please click the button below to verify your email address:</p>
<a href="{verify_url}" class="btn">Verify Email</a>
<p>If the button doesn't work, copy this link:</p>
<p class="code">{verify_url}</p>
<p class="small">This link expires in {VERIFICATION_TOKEN_EXPIRY_HOURS} hours.</p>
</div></body></html>"""
        text = f"Verify your email for {brand}:\n{verify_url}\n\nThis link expires in {VERIFICATION_TOKEN_EXPIRY_HOURS} hours."
        return subject, html, text

    def render_otp_email(self, otp_code: str, full_name: str = "") -> Tuple[str, str, str]:
        """Return (subject, html, text) for the OTP login email."""
        brand = self._brand()
        subject = f"Your {brand} login code: {otp_code}"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body {{ font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px; }}
.card {{ max-width: 480px; margin: 0 auto; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
h1 {{ color: #25D366; margin-top: 0; }}
.code-box {{ background: #f0f7f0; border: 2px dashed #25D366; border-radius: 8px; padding: 24px; text-align: center; margin: 20px 0; }}
.code {{ font-size: 36px; font-weight: bold; color: #25D366; letter-spacing: 8px; font-family: monospace; }}
.small {{ color: #888; font-size: 12px; margin-top: 24px; }}
</style></head><body>
<div class="card">
<h1>Your login code</h1>
<p>Hi{(' ' + full_name) if full_name else ''},</p>
<p>Use the code below to sign in to {brand}:</p>
<div class="code-box">
<span class="code">{otp_code}</span>
</div>
<p class="small">This code expires in {OTP_EXPIRY_MINUTES} minutes. Do not share it.</p>
</div></body></html>"""
        text = f"Your {brand} login code: {otp_code}\n\nThis code expires in {OTP_EXPIRY_MINUTES} minutes."
        return subject, html, text

    def render_password_reset_email(self, token: str, full_name: str = "") -> Tuple[str, str, str]:
        """Return (subject, html, text) for the password-reset link."""
        brand = self._brand()
        reset_url = f"{BASE_URL}/reset-password?token={token}"
        subject = f"Reset your {brand} password"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>body {{ font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px; }}
.card {{ max-width: 480px; margin: 0 auto; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
h1 {{ color: #e74c3c; margin-top: 0; }}
.btn {{ display: inline-block; background: #e74c3c; color: white; text-decoration: none; padding: 12px 28px; border-radius: 8px; font-weight: bold; margin: 16px 0; }}
.code {{ font-family: monospace; background: #f0f0f0; padding: 8px 12px; border-radius: 4px; font-size: 14px; word-break: break-all; }}
.small {{ color: #888; font-size: 12px; margin-top: 24px; }}
</style></head><body>
<div class="card">
<h1>Reset your password</h1>
<p>Hi{(' ' + full_name) if full_name else ''},</p>
<p>Click the button below to reset your password. This link is valid for {PASSWORD_RESET_EXPIRY_HOURS} hour(s) only:</p>
<a href="{reset_url}" class="btn">Reset Password</a>
<p>If the button doesn't work, copy this link:</p>
<p class="code">{reset_url}</p>
<p class="small">If you didn't request a password reset, you can safely ignore this email.</p>
</div></body></html>"""
        text = f"Reset your {brand} password:\n{reset_url}\n\nThis link expires in {PASSWORD_RESET_EXPIRY_HOURS} hour(s)."
        return subject, html, text


# ---------------------------------------------------------------------------
# OTP / Email Auth Service
# ---------------------------------------------------------------------------

class EmailAuthService:
    """
    Orchestrates the full email-otp auth lifecycle:
      - request_email_verification(email)
      - verify_email(token)
      - request_otp(email)              → OTP login
      - verify_otp(email, otp)         → returns access token
      - request_password_reset(email)
      - reset_password(token, password)
    """

    def __init__(self):
        self.email_service = EmailService()

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _generate_otp(length: int = OTP_LENGTH) -> str:
        """Generate a random numeric OTP of the given length."""
        return "".join(secrets.choice("0123456789") for _ in range(length))

    @staticmethod
    def _generate_token() -> str:
        """Generate a cryptographically secure URL-safe token."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def _is_rate_limited(email: str) -> bool:
        """Check if the email has exceeded the OTP request rate limit."""
        import time
        now = time.time()
        bucket = _otp_rate_buckets.get(email, [])
        # Prune entries older than 60 seconds
        bucket = [t for t in bucket if now - t < 60]
        if len(bucket) >= _OTP_RATE_MAX_PER_MIN:
            _otp_rate_buckets[email] = bucket
            return True
        bucket.append(now)
        _otp_rate_buckets[email] = bucket
        return False

    # -- Email verification --------------------------------------------------

    async def request_email_verification(self, email: str) -> Dict[str, Any]:
        """Send a verification email to the given address."""
        # Lazy import to avoid circular dependency
        from auth import User, EmailVerification

        if not email or "@" not in email:
            return {"status": "error", "message": "Valid email is required"}

        async with async_session() as session:
            user = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()

            if not user:
                # Don't reveal whether the email exists (security best practice)
                return {
                    "status": "sent",
                    "message": "If the email exists in our system, a verification link has been sent.",
                }

            if user.is_email_verified:
                return {
                    "status": "already_verified",
                    "message": "Email is already verified",
                    "email": email,
                }

            token = self._generate_token()
            token_hash = _hash_value(token)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)

            # Invalidate any previous verification tokens for this email+purpose
            await session.execute(
                delete(EmailVerification).where(
                    and_(
                        EmailVerification.email == email,
                        EmailVerification.purpose == "email_verification",
                    )
                )
            )

            verification = EmailVerification(
                email=email,
                token_hash=token_hash,
                purpose="email_verification",
                expires_at=expires_at,
                user_id=user.id,
            )
            session.add(verification)
            await session.commit()

        # Send email (outside the DB session)
        subject, html, text = self.email_service.render_verification_email(token, user.full_name)
        success, msg = self.email_service.send_email(email, subject, html, text)

        logger.info(f"Verification email {'sent' if success else 'failed'} to {email}")
        return {
            "status": "sent" if success else "error",
            "message": msg,
            "email": email,
        }

    async def verify_email(self, token: str) -> Dict[str, Any]:
        """Verify an email address using a verification token."""
        from auth import User, EmailVerification

        if not token:
            return {"status": "error", "message": "Token is required"}

        token_hash = _hash_value(token)
        now = datetime.now(timezone.utc)

        async with async_session() as session:
            verification = (await session.execute(
                select(EmailVerification).where(
                    and_(
                        EmailVerification.token_hash == token_hash,
                        EmailVerification.purpose == "email_verification",
                        EmailVerification.used == False,
                    )
                )
            )).scalar_one_or_none()

            if not verification:
                return {"status": "error", "message": "Invalid verification token"}

            if verification.expires_at < now:
                return {"status": "error", "message": "Verification token has expired"}

            # Mark user as verified
            user = (await session.execute(
                select(User).where(User.id == verification.user_id)
            )).scalar_one_or_none()
            if user:
                user.is_email_verified = True
                verification.used = True
                await session.commit()
                logger.info(f"[v] Email verified for user {user.id} ({user.email})")
                return {
                    "status": "verified",
                    "message": "Email verified successfully",
                    "email": verification.email,
                }

            return {"status": "error", "message": "User not found"}

    # -- OTP login (passwordless) -------------------------------------------

    async def request_otp(self, email: str) -> Dict[str, Any]:
        """Generate and send a 6-digit OTP to the email for passwordless login."""
        from auth import User, EmailVerification

        if not email or "@" not in email:
            return {"status": "error", "message": "Valid email is required"}

        if self._is_rate_limited(email):
            return {
                "status": "error",
                "message": "Too many OTP requests. Please wait a minute and try again.",
            }

        async with async_session() as session:
            user = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()

            if not user:
                # Don't reveal whether the email exists
                return {
                    "status": "sent",
                    "message": "If the email exists in our system, an OTP has been sent.",
                }

            if not user.is_active:
                return {"status": "error", "message": "Account is deactivated"}

            otp_code = self._generate_otp()
            otp_hash = _hash_value(otp_code)
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

            # Invalidate previous OTPs for this email
            await session.execute(
                delete(EmailVerification).where(
                    and_(
                        EmailVerification.email == email,
                        EmailVerification.purpose == "otp_login",
                    )
                )
            )

            record = EmailVerification(
                email=email,
                token_hash=_hash_value(self._generate_token()),  # dummy token_hash for lookup
                purpose="otp_login",
                otp_code_hash=otp_hash,
                expires_at=expires_at,
                user_id=user.id,
            )
            session.add(record)
            await session.commit()

        # Send OTP email
        subject, html, text = self.email_service.render_otp_email(otp_code, user.full_name)
        success, msg = self.email_service.send_email(email, subject, html, text)

        logger.info(f"OTP {'sent' if success else 'failed'} to {email}")
        return {
            "status": "sent" if success else "error",
            "message": msg if success else f"Failed to send OTP: {msg}",
            "email": email,
        }

    async def verify_otp(self, email: str, otp: str) -> Dict[str, Any]:
        """Verify an OTP and return a JWT access token if valid."""
        from auth import User, EmailVerification, create_access_token

        if not email or not otp:
            return {"status": "error", "message": "Email and OTP are required"}

        otp_hash = _hash_value(otp)
        now = datetime.now(timezone.utc)

        async with async_session() as session:
            record = (await session.execute(
                select(EmailVerification).where(
                    and_(
                        EmailVerification.email == email,
                        EmailVerification.purpose == "otp_login",
                        EmailVerification.otp_code_hash == otp_hash,
                        EmailVerification.used == False,
                    )
                )
            )).scalar_one_or_none()

            if not record:
                return {"status": "error", "message": "Invalid OTP"}

            if record.expires_at < now:
                return {"status": "error", "message": "OTP has expired"}

            user = (await session.execute(
                select(User).where(User.id == record.user_id)
            )).scalar_one_or_none()
            if not user or not user.is_active:
                return {"status": "error", "message": "User not found or inactive"}

            # Mark OTP as used
            record.used = True
            user.last_login = now
            await session.commit()

            token = create_access_token(
                user_id=user.id,
                email=user.email,
                role=user.role,
                client_id=user.client_id,
            )

            from auth import JWT_EXPIRE_HOURS
            logger.info(f"[v] OTP login successful for user {user.id} ({user.email})")
            return {
                "status": "ok",
                "access_token": token,
                "token_type": "bearer",
                "expires_in": JWT_EXPIRE_HOURS * 3600,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                    "client_id": user.client_id,
                    "is_email_verified": user.is_email_verified,
                },
            }

    # -- Password reset ------------------------------------------------------

    async def request_password_reset(self, email: str) -> Dict[str, Any]:
        """Send a password-reset link to the email."""
        from auth import User, EmailVerification

        if not email or "@" not in email:
            return {"status": "error", "message": "Valid email is required"}

        if self._is_rate_limited(email):
            return {
                "status": "error",
                "message": "Too many reset requests. Please wait a minute and try again.",
            }

        async with async_session() as session:
            user = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()

            if not user:
                # Don't reveal whether the email exists
                return {
                    "status": "sent",
                    "message": "If the email exists in our system, a reset link has been sent.",
                }

            token = self._generate_token()
            token_hash = _hash_value(token)
            expires_at = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_EXPIRY_HOURS)

            # Invalidate previous reset tokens for this email
            await session.execute(
                delete(EmailVerification).where(
                    and_(
                        EmailVerification.email == email,
                        EmailVerification.purpose == "password_reset",
                    )
                )
            )

            record = EmailVerification(
                email=email,
                token_hash=token_hash,
                purpose="password_reset",
                expires_at=expires_at,
                user_id=user.id,
            )
            session.add(record)
            await session.commit()

        # Send email
        subject, html, text = self.email_service.render_password_reset_email(token, user.full_name)
        success, msg = self.email_service.send_email(email, subject, html, text)

        logger.info(f"Password reset {'sent' if success else 'failed'} to {email}")
        return {
            "status": "sent" if success else "error",
            "message": msg,
            "email": email,
        }

    async def reset_password(self, token: str, new_password: str) -> Dict[str, Any]:
        """Reset a user's password using a valid reset token."""
        from auth import User, EmailVerification, hash_password

        if not token or not new_password:
            return {"status": "error", "message": "Token and new password are required"}

        if len(new_password) < 8:
            return {"status": "error", "message": "Password must be at least 8 characters"}

        token_hash = _hash_value(token)
        now = datetime.now(timezone.utc)

        async with async_session() as session:
            record = (await session.execute(
                select(EmailVerification).where(
                    and_(
                        EmailVerification.token_hash == token_hash,
                        EmailVerification.purpose == "password_reset",
                        EmailVerification.used == False,
                    )
                )
            )).scalar_one_or_none()

            if not record:
                return {"status": "error", "message": "Invalid or expired reset token"}

            if record.expires_at < now:
                return {"status": "error", "message": "Reset token has expired"}

            user = (await session.execute(
                select(User).where(User.id == record.user_id)
            )).scalar_one_or_none()
            if not user:
                return {"status": "error", "message": "User not found"}

            user.password_hash = hash_password(new_password)
            record.used = True
            await session.commit()

            logger.info(f"[v] Password reset for user {user.id} ({user.email})")
            return {
                "status": "ok",
                "message": "Password reset successfully",
            }

    # -- Helpers -------------------------------------------------------------

    async def get_verification_status(self, email: str) -> Dict[str, Any]:
        """Check whether an email is verified."""
        from auth import User

        if not email:
            return {"status": "error", "message": "Email is required"}

        async with async_session() as session:
            user = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()

            if not user:
                return {"status": "error", "message": "User not found"}

            return {
                "email": user.email,
                "is_email_verified": user.is_email_verified,
                "is_active": user.is_active,
            }


# Singleton instance
email_auth_service = EmailAuthService()
