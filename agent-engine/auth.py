"""
JWT-based authentication with role-based access control (RBAC).

Provides:
  - Password hashing (bcrypt)
  - JWT token creation / verification
  - FastAPI dependency: get_current_user, require_role
  - Default roles: admin, agent, client, viewer
  - API key authentication (for public REST API)
"""
import os
import secrets
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

import jwt
import bcrypt
from fastapi import Depends, HTTPException, status, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, Boolean, Integer, JSON

from db import Base, async_session, get_session
from config import settings
from logging_setup import get_logger

logger = get_logger("auth")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

JWT_SECRET = settings.jwt_secret_key or os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(64)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

security = HTTPBearer(auto_error=False)

# In-memory token blacklist for logout (JTI-based)
_blacklisted_jtis: set = set()


def blacklist_token(jti: str):
    """Add a token's JTI to the blacklist (logout)."""
    _blacklisted_jtis.add(jti)


def is_token_blacklisted(jti: str) -> bool:
    """Check if a token JTI is blacklisted."""
    return jti in _blacklisted_jtis


class Role(str, Enum):
    """User roles for RBAC"""
    ADMIN = "admin"          # Full access (platform owner)
    AGENT = "agent"          # Human agent handling handoffs
    CLIENT = "client"        # Business owner (tenant)
    VIEWER = "viewer"        # Read-only dashboard access


# Role hierarchy (higher number = more privileges)
ROLE_HIERARCHY = {
    Role.VIEWER: 1,
    Role.CLIENT: 2,
    Role.AGENT: 3,
    Role.ADMIN: 4,
}


# ---------------------------------------------------------------------------
# DB Models
# ---------------------------------------------------------------------------

class User(Base):
    """Platform users (admins, agents, clients, viewers)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.CLIENT.value)
    client_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)  # multi-tenant link
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    """Audit trail for every admin action (GDPR/compliance)."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource: Mapped[Optional[str]] = mapped_column(String(100))
    resource_id: Mapped[Optional[str]] = mapped_column(String(100))
    ip_address: Mapped[Optional[str]] = mapped_column(String(50))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class EmailVerification(Base):
    """Email verification, OTP login, and password-reset tokens."""
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    token_hash: Mapped[str] = mapped_column(String(255), index=True)
    purpose: Mapped[str] = mapped_column(String(50), default="email_verification")
    # When purpose == "otp_login", the OTP code is stored hashed in otp_code_hash
    otp_code_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict[str, Any]


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = Role.CLIENT.value
    client_id: Optional[int] = None


# -- Email / OTP auth schemas --

class EmailVerifyRequest(BaseModel):
    """Request a verification email be sent to this address."""
    email: str


class EmailVerifyConfirmRequest(BaseModel):
    """Confirm email verification (for the link-based flow)."""
    token: str


class OTPRequest(BaseModel):
    """Request a one-time password be sent to an email (passwordless login)."""
    email: str


class OTPVerifyRequest(BaseModel):
    """Verify an OTP and return a JWT access token."""
    email: str
    otp: str


class PasswordResetRequest(BaseModel):
    """Request a password-reset link be sent to an email."""
    email: str


class PasswordResetConfirmRequest(BaseModel):
    """Reset password using a reset token."""
    token: str
    password: str


class PasswordChangeRequest(BaseModel):
    """Change password for an authenticated user (requires current password)."""
    current_password: str
    new_password: str


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        pwd_bytes = plain.encode('utf-8')[:72]
        return bcrypt.checkpw(pwd_bytes, hashed.encode('utf-8'))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int, email: str, role: str,
                        client_id: Optional[int] = None,
                        expires_hours: int = JWT_EXPIRE_HOURS) -> str:
    """Create a signed JWT access token."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "client_id": client_id,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if is_token_blacklisted(payload.get("jti", "")):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked (logged out)")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")


def generate_api_key() -> str:
    """Generate a secure API key (prefix-wap-...)."""
    return f"wap_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    """Hash an API key for storage (sha256)."""
    return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

async def create_user(email: str, password: str, full_name: str,
                      role: str = Role.CLIENT.value,
                      client_id: Optional[int] = None) -> User:
    """Create a new user."""
    async with async_session() as session:
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            client_id=client_id,
            api_key=generate_api_key() if role == Role.CLIENT.value else None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def authenticate(email: str, password: str) -> Optional[User]:
    """Verify credentials and return the User, or None."""
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        user.last_login = datetime.now(timezone.utc)
        await session.commit()
        return user


async def get_user_by_api_key(api_key: str) -> Optional[User]:
    """Look up a user by API key (sha256 hashed for storage)."""
    key_hash = hash_api_key(api_key)
    async with async_session() as session:
        return (await session.execute(select(User).where(User.api_key == key_hash))).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

async def log_action(user_id: Optional[int], action: str,
                     resource: Optional[str] = None, resource_id: Optional[str] = None,
                     ip_address: Optional[str] = None, user_agent: Optional[str] = None,
                     metadata: Optional[dict] = None):
    """Record an audit-log entry."""
    try:
        async with async_session() as session:
            entry = AuditLog(
                user_id=user_id, action=action, resource=resource, resource_id=resource_id,
                ip_address=ip_address, user_agent=user_agent, metadata_json=metadata or {},
            )
            session.add(entry)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to write audit log: {e}")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> User:
    """Resolve the current user from Bearer token OR X-API-Key header."""
    api_key = request.headers.get("X-API-Key")
    if api_key:
        user = await get_user_by_api_key(api_key)
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        return user

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication (Bearer token or X-API-Key required)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    user_id = int(payload.get("sub"))
    async with async_session() as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        return user


def require_role(*allowed_roles: Role):
    """Dependency factory: ensure the current user has one of the allowed roles."""
    async def _checker(user: User = Depends(get_current_user)) -> User:
        if Role(user.role) not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' not authorized. Required: {[r.value for r in allowed_roles]}",
            )
        return user
    return _checker


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Shorthand for require_role(Role.ADMIN)."""
    if Role(user.role) != Role.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user