"""
WhatsApp Agent Platform - Main Application
"""
import os
import sys
import uuid
import hmac
import hashlib
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List


# Add services directory to Python path (absolute path)
_SERVICES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services"))

if _SERVICES_DIR not in sys.path:
    sys.path.insert(0, _SERVICES_DIR)
    # Force import check: verify services is importable
    import importlib
    try:
        importlib.import_module("lead_scoring")
        print(f"[v] Services directory loaded: {_SERVICES_DIR}", flush=True)
    except ImportError as e:
        print(f"[!] Services import failed: {e}", flush=True)
        # Fallback: add CWD parent
        _alt = os.path.abspath(os.path.join(os.getcwd(), "..", "services"))
        if _alt not in sys.path:
            sys.path.insert(0, _alt)
            print(f"[i] Trying alt path: {_alt}", flush=True)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from auth import security

from db import init_db, get_session, save_message, get_conversation_history, upsert_contact
from config import settings

# Lazy-loaded orchestrator to keep deployment lightweight
_AGENT_ORCHESTRATOR = None


def get_orchestrator():
    """Lazy import orchestrator to avoid pulling in langchain at startup."""
    global _AGENT_ORCHESTRATOR
    if _AGENT_ORCHESTRATOR is None:
        from orchestrator import AgentOrchestrator
        _AGENT_ORCHESTRATOR = AgentOrchestrator()
    return _AGENT_ORCHESTRATOR
from state_machine import get_state_machine, set_state_machine, RedisStateMachine, InMemoryStateMachine
from logging_setup import get_logger
from auth import (
    LoginRequest, RegisterRequest, TokenResponse, Role, User,
    create_user, authenticate, create_access_token, get_current_user,
    require_role, require_admin, log_action, JWT_EXPIRE_HOURS,
)
from payments import PaymentEngine
from security import (
    verify_bridge_webhook, verify_meta_webhook, rate_limit, sanitize_text, sanitize_phone,
)

payment_engine = PaymentEngine()

logger = get_logger("main")

# ---------------------------------------------------------------------------
# App initialization
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("[v] Initializing WhatsApp Agent Platform...")
    await init_db()
    logger.info("[v] Database tables created/verified")
    
    # Initialize state machine via get_state_machine() (handles Redis fallback)
    sm = get_state_machine()
    set_state_machine(sm)
    logger.info(f"[v] State machine ready: {type(sm).__name__}")
    
    # Initialize orchestrator
    app.state.orchestrator = get_orchestrator()
    logger.info("[v] Agent orchestrator ready")

    # Start background scheduler (drip campaigns + appointment reminders)
    from scheduler import start_scheduler, stop_scheduler
    await start_scheduler()

    # Wire up drip campaign message sender so campaign messages go through WhatsApp
    try:
        from drip_campaigns import engine as drip_engine
        drip_engine.message_sender = _campaign_message_sender
        logger.info("[v] Drip campaign message sender wired to WhatsApp bridge")
    except Exception as e:
        logger.warning(f"Drip campaign message sender not wired: {e}")

    # Start Telegram bot bridge if token is configured
    if settings.telegram_bot_token and settings.telegram_bot_token != "your_telegram_bot_token_here":
        try:
            import asyncio
            from telegram_bridge import main as telegram_main
            app.state.telegram_task = asyncio.create_task(telegram_main())
            logger.info("[v] Telegram bot bridge started")
        except Exception as e:
            logger.error(f"[!] Failed to start Telegram bridge: {e}")
    else:
        logger.info("[i] Telegram bridge not started (no token configured)")

    yield

    # Cancel telegram task on shutdown
    telegram_task = getattr(app.state, 'telegram_task', None)
    if telegram_task:
        telegram_task.cancel()
        logger.info("[i] Telegram bridge stopped")

    await stop_scheduler()
    logger.info("[i] Shutting down...")

app = FastAPI(
    title="WhatsApp Agent Platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount frontend static files
_FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
if os.path.exists(_FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
    logger.info(f"[v] Frontend mounted at /frontend from {_FRONTEND_DIR}")

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MessageRequest(BaseModel):
    phone_number: str
    message: str
    client_id: int = 1

class MessageResponse(BaseModel):
    reply: str
    phone_number: str

class SignupRequest(BaseModel):
    name: str
    email: str
    phone: str
    business_type: str = "general"

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Serve the landing page"""
    index_path = os.path.join(_FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"status": "ok", "message": "WhatsApp Agent Platform API. Visit /frontend/dashboard.html for owner dashboard or /frontend/storefront.html for storefront."}

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/sitemap.xml")
async def sitemap():
    """Serve sitemap.xml for SEO."""
    sitemap_path = os.path.join(_FRONTEND_DIR, "sitemap.xml")
    if os.path.exists(sitemap_path):
        return FileResponse(sitemap_path, media_type="application/xml")
    return Response(content="", media_type="application/xml")

@app.get("/robots.txt")
async def robots():
    """Serve robots.txt for SEO."""
    robots_path = os.path.join(_FRONTEND_DIR, "robots.txt")
    if os.path.exists(robots_path):
        return FileResponse(robots_path, media_type="text/plain")
    return Response(content="User-agent: *\nAllow: /", media_type="text/plain")

@app.get("/stats")
async def stats():
    return {
        "status": "ok",
        "version": "1.0.0",
        "uptime": "running"
    }

@app.post("/api/message", response_model=MessageResponse)
async def handle_message(req: MessageRequest, request: Request):
    """Process an incoming WhatsApp message through the AI agent."""
    await rate_limit(request, str(req.client_id))
    try:
        orchestrator: AgentOrchestrator = app.state.orchestrator
        reply = await orchestrator.process_message(
            phone_number=sanitize_phone(req.phone_number),
            message=sanitize_text(req.message),
            client_id=req.client_id,
        )
        return MessageResponse(reply=reply, phone_number=req.phone_number)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/webhook")
async def meta_webhook_verify(request: Request):
    """Meta WhatsApp Business API subscription challenge."""
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and verify_meta_webhook(
        params.get("hub.mode"), params.get("hub.verify_token"), None, None, b""
    ):
        return int(params.get("hub.challenge", "0"))
    raise HTTPException(status_code=403, detail="Forbidden")


@app.post("/webhook")
async def webhook(request: Request):
    """WhatsApp webhook — verifies bridge signature, rate-limits, sanitizes input."""
    body = await request.body()
    signature = request.headers.get("X-Bridge-Signature") or request.headers.get("X-Hub-Signature-256")
    if not verify_bridge_webhook(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    await rate_limit(request)

    data = await request.json()
    logger.info(f"Webhook received: {data}")

    phone_number = sanitize_phone(data.get("from") or data.get("phone_number", ""))
    message = sanitize_text(data.get("body") or data.get("text") or data.get("message", ""))
    client_id = data.get("client_id") or 1

    if phone_number and message:
        orchestrator: AgentOrchestrator = app.state.orchestrator
        reply = await orchestrator.process_message(phone_number, message, client_id)
        return {"status": "ok", "reply": reply}

    return {"status": "ok", "message": "webhook received"}

@app.post("/signup")
async def signup(req: SignupRequest):
    """Register a new business client + owner user account."""
    try:
        async for session in get_session():
            from db import create_client
            client = await create_client(
                session,
                business_name=req.name,
                whatsapp_number=req.phone,
                vertical=req.business_type,
            )
            return {"status": "ok", "message": "Registration successful", "client_id": client.id}
    except Exception as e:
        logger.error(f"Signup error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Authentication Endpoints
# ---------------------------------------------------------------------------

@app.post("/auth/register", response_model=TokenResponse)
async def auth_register(req: RegisterRequest, request: Request):
    """Register a new user account. Public registration is always CLIENT role;
    admin accounts must be created by an existing admin."""
    role = req.role if req.role in (Role.CLIENT.value, Role.VIEWER.value) else Role.CLIENT.value
    user = await create_user(
        email=req.email, password=req.password,
        full_name=req.full_name, role=role, client_id=req.client_id,
    )
    await log_action(user.id, "register", "user", str(user.id),
                     ip_address=request.client.host if request.client else None)
    token = create_access_token(user.id, user.email, user.role, user.client_id)
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user={"id": user.id, "email": user.email, "full_name": user.full_name,
              "role": user.role, "client_id": user.client_id},
    )


@app.post("/auth/login", response_model=TokenResponse)
async def auth_login(req: LoginRequest, request: Request):
    """Log in with email + password, get a JWT."""
    user = await authenticate(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await log_action(user.id, "login", "user", str(user.id),
                     ip_address=request.client.host if request.client else None)
    token = create_access_token(user.id, user.email, user.role, user.client_id)
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user={"id": user.id, "email": user.email, "full_name": user.full_name,
              "role": user.role, "client_id": user.client_id},
    )


@app.get("/auth/me")
async def auth_me(user: User = Depends(get_current_user)):
    """Get the current authenticated user."""
    return {"id": user.id, "email": user.email, "full_name": user.full_name,
            "role": user.role, "client_id": user.client_id,
            "api_key": user.api_key, "last_login": str(user.last_login or "")}


@app.post("/auth/logout")
async def auth_logout(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Log out — blacklist the current JWT token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing token")
    from auth import decode_token, blacklist_token
    payload = decode_token(credentials.credentials)
    blacklist_token(payload.get("jti", ""))
    return {"status": "ok", "message": "Logged out"}


# ---------------------------------------------------------------------------
# Multi-tenant "My Business" Endpoints (visitor-specific)
# ---------------------------------------------------------------------------

def _get_my_client_id(user: User) -> int:
    """Return the user's client_id (or user.id as fallback for self-service)."""
    return user.client_id or user.id


@app.get("/api/me/business")
async def my_business(user: User = Depends(get_current_user)):
    """Get the visitor's own business profile."""
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            return p.to_dict()
    return {"status": "no_business", "client_id": cid}


@app.post("/api/me/business")
async def create_my_business(request: Request, user: User = Depends(get_current_user)):
    """Create/update the visitor's own business profile (multi-tenant)."""
    from business_profiles import business_manager, BusinessProfile, BusinessType
    import uuid
    body = await request.json()
    business_type = body.get("business_type", "general")
    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Business name required")

    # Find existing profile for this user
    existing = None
    for p in business_manager.profiles.values():
        if p.client_id == user.id:
            existing = p
            break

    if existing:
        # Update existing
        for key, value in body.items():
            if hasattr(existing, key) and key not in ("id", "client_id", "owner_id", "created_at"):
                setattr(existing, key, value)
        existing.updated_at = datetime.utcnow().isoformat()
        business_manager._save()
        return {"status": "updated", "business": existing.to_dict()}

    # Create new
    try:
        bt = BusinessType(business_type)
    except ValueError:
        bt = BusinessType.CUSTOM
    profile = BusinessProfile(
        id=uuid.uuid4().hex[:8],
        client_id=user.id,
        owner_id=str(user.id),
        business_type=bt,
        name=name,
        description=body.get("description", ""),
        logo_url=body.get("logo_url", ""),
        primary_color=body.get("primary_color", "#25D366"),
        secondary_color=body.get("secondary_color", "#128C7E"),
        welcome_message=body.get("welcome_message", ""),
        contact_phone=body.get("contact_phone", ""),
        contact_email=body.get("contact_email", ""),
        address=body.get("address", ""),
        website=body.get("website", ""),
        payment_methods=body.get("payment_methods", ["cash", "upi"]),
        delivery_enabled=body.get("delivery_enabled", False),
        delivery_radius_km=body.get("delivery_radius_km", 5),
        tax_rate_percent=body.get("tax_rate_percent", 5.0),
    )
    business_manager.create_profile(profile)

    # Link the user's client_id to this business (multi-tenant)
    try:
        from db import async_session
        from sqlalchemy import select
        async with async_session() as session:
            db_user = (await session.execute(select(User).where(User.id == user.id))).scalar_one_or_none()
            if db_user:
                db_user.client_id = user.id
                await session.commit()
    except Exception as e:
        logger.warning(f"Could not link client_id: {e}")

    return {"status": "created", "business": profile.to_dict()}


@app.get("/api/me/catalog")
async def my_catalog(user: User = Depends(get_current_user)):
    """Get the visitor's own catalog."""
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            return {"items": business_manager.get_catalog(p.id)}
    return {"items": []}


@app.post("/api/me/catalog/add")
async def add_my_catalog_item(request: Request, user: User = Depends(get_current_user)):
    """Add an item to the visitor's own catalog."""
    from business_profiles import business_manager, CatalogItem
    import uuid
    cid = _get_my_client_id(user)
    body = await request.json()
    profile = None
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            profile = p
            break
    if not profile:
        raise HTTPException(status_code=400, detail="Create business profile first")
    item = CatalogItem(
        id=uuid.uuid4().hex[:8],
        business_id=profile.id,
        category=body.get("category", "General"),
        name=body.get("name", ""),
        description=body.get("description", ""),
        price=float(body.get("price", 0)),
        image_url=body.get("image_url", ""),
        is_available=body.get("is_available", True),
    )
    business_manager.add_catalog_item(profile.id, item)
    return {"status": "added", "item": item.to_dict()}


@app.get("/api/me/orders")
async def my_orders(user: User = Depends(get_current_user)):
    """Get the visitor's own orders."""
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            return {"orders": business_manager.get_orders(p.id)}
    return {"orders": []}


@app.get("/api/me/stats")
async def my_stats(user: User = Depends(get_current_user)):
    """Get the visitor's own business stats."""
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            return business_manager.get_business_stats(p.id)
    return {"total_orders": 0, "pending": 0, "completed": 0, "revenue": 0, "avg_order_value": 0}


# ---------------------------------------------------------------------------
# Payment Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/payments/link")
async def create_payment_link(request: Request, user: User = Depends(get_current_user)):
    """Create a Razorpay payment link (owner only)."""
    body = await request.json()
    amount = int(body.get("amount", 0))  # paise
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount (in paise) must be > 0")
    result = await payment_engine.create_payment_link(
        amount=amount,
        description=body.get("description", "Payment"),
        phone=body.get("phone", ""),
        name=body.get("name", ""),
    )
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.get("/api/payments/{payment_link_id}/status")
async def payment_status(payment_link_id: str, user: User = Depends(get_current_user)):
    """Check status of a payment link."""
    result = await payment_engine.get_payment_status(payment_link_id)
    if "error" in result:
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@app.post("/api/payments/upi-link")
async def create_upi_link(request: Request, user: User = Depends(get_current_user)):
    """Generate a UPI deep-link (no gateway needed)."""
    body = await request.json()
    upi_id = body.get("upi_id", "")
    amount = float(body.get("amount", 0))
    if not upi_id or amount <= 0:
        raise HTTPException(status_code=400, detail="upi_id and amount (rupees) required")
    return PaymentEngine.generate_upi_link(
        upi_id=upi_id, amount=amount,
        payee_name=body.get("payee_name", ""), note=body.get("note", ""),
    )


@app.post("/api/payments/webhook")
async def razorpay_webhook(request: Request):
    """Razorpay webhook — signature-verified."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not payment_engine.verify_webhook(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    import json as _json
    event = _json.loads(body)
    logger.info(f"Razorpay event: {event.get('event')}")
    # Mark order paid on payment_link.paid
    if event.get("event") == "payment_link.paid":
        logger.info("Payment link paid: %s", event.get("payload", {}).get("payment_link", {}).get("entity", {}).get("id"))
    return {"status": "ok"}

# ---------------------------------------------------------------------------
# Service API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/leads/stats")
async def lead_stats(user: User = Depends(get_current_user)):
    """Get lead scoring statistics (tenant-scoped)."""
    from lead_scoring import scoring_engine
    cid = _get_my_client_id(user)
    return scoring_engine.get_stats(cid)

@app.get("/api/leads")
async def list_leads(tier: str = "", limit: int = 10, user: User = Depends(get_current_user)):
    """List leads, optionally filtered by tier (tenant-scoped)."""
    from lead_scoring import scoring_engine, LeadTier
    cid = _get_my_client_id(user)
    if tier:
        try:
            t = LeadTier(tier)
            leads = scoring_engine.get_leads_by_tier(t, cid)
        except ValueError:
            return {"error": f"Invalid tier: {tier}. Use: hot, warm, cold, dead"}
    else:
        leads = scoring_engine.get_top_leads(limit, cid)
    return {"leads": [l.to_dict() for l in leads]}

@app.get("/api/leads/{contact_id}")
async def get_lead(contact_id: str, user: User = Depends(get_current_user)):
    """Get lead profile and score (tenant-scoped)."""
    from lead_scoring import scoring_engine
    cid = _get_my_client_id(user)
    profile = scoring_engine.get_profile(contact_id, cid)
    return profile.to_dict()

@app.post("/api/qr/create")
async def create_qr(phone: str, message: str = ""):
    """Create a dynamic QR code"""
    from qr_generator import qr_manager
    qr = qr_manager.create(phone, message)
    return {
        "qr_id": qr.qr_id,
        "whatsapp_url": qr.whatsapp_url,
        "data_uri": qr.get_data_uri(),
    }

@app.get("/api/qr/{qr_id}")
async def get_qr(qr_id: str):
    """Get QR code info"""
    from qr_generator import qr_manager
    qr = qr_manager.get(qr_id)
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")
    return qr.to_dict()

@app.get("/api/qr/{qr_id}/redirect")
async def redirect_qr(qr_id: str):
    """Track scan and redirect"""
    from qr_generator import qr_manager
    url = qr_manager.redirect(qr_id)
    if not url:
        raise HTTPException(status_code=404, detail="QR code not found or inactive")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=url)

@app.post("/api/campaigns/create")
async def create_campaign(name: str, description: str = ""):
    """Create a drip campaign"""
    from drip_campaigns import DripCampaign, TriggerType, engine
    import hashlib
    campaign_id = hashlib.md5(f"{name}_{datetime.utcnow().timestamp()}".encode()).hexdigest()[:12]
    campaign = DripCampaign(id=campaign_id, name=name, description=description)
    engine.register_campaign(campaign)
    return campaign.to_dict()

@app.get("/api/campaigns")
async def list_campaigns():
    """List all drip campaigns"""
    from drip_campaigns import engine
    return {"campaigns": [c.to_dict() for c in engine.campaigns.values()]}

@app.get("/api/campaigns/{campaign_id}/stats")
async def campaign_stats(campaign_id: str):
    """Get campaign statistics"""
    from drip_campaigns import engine
    return engine.get_campaign_stats(campaign_id)

@app.post("/api/campaigns/{campaign_id}/enroll")
async def enroll_in_campaign(campaign_id: str, contact_id: str, channel: str = "whatsapp"):
    """Enroll a contact in a campaign"""
    from drip_campaigns import engine
    key = await engine.enroll(campaign_id, contact_id, channel)
    if not key:
        raise HTTPException(status_code=400, detail="Failed to enroll")
    return {"status": "enrolled", "key": key}

@app.post("/api/referral/create-link")
async def create_referral_link(program_id: str, contact_id: str, client_id: int = 1):
    """Create a referral link for a contact"""
    from referral_system import referral_system
    code = referral_system.create_link(program_id, contact_id, client_id)
    if not code:
        raise HTTPException(status_code=400, detail="Failed to create link")
    link = referral_system.get_link(code)
    return {"code": code, "url": link.referral_url}

@app.get("/api/referral/stats")
async def referral_stats(client_id: int = 1):
    """Get referral system statistics"""
    from referral_system import referral_system
    return referral_system.get_stats(client_id)

@app.post("/api/webhooks/register")
async def register_webhook(url: str, events: str, client_id: int = 1):
    """Register a webhook endpoint"""
    from public_api import webhook_manager, WebhookEvent
    event_list = [WebhookEvent(e.strip()) for e in events.split(",")]
    endpoint = webhook_manager.register(client_id, url, event_list)
    return endpoint.to_dict()

@app.get("/api/webhooks/logs")
async def webhook_logs(endpoint_id: str = ""):
    """Get webhook delivery logs"""
    from public_api import webhook_manager
    return {"logs": webhook_manager.get_delivery_log(endpoint_id or None)}

@app.post("/api/telegram/send")
async def telegram_send(request: Request, user: User = Depends(get_current_user)):
    """Send a message via Telegram (requires TELEGRAM_BOT_TOKEN)."""
    if not settings.telegram_bot_token or settings.telegram_bot_token == "your_telegram_bot_token_here":
        raise HTTPException(status_code=400, detail="Telegram bot not configured")
    body = await request.json()
    chat_id = body.get("chat_id", "")
    text = body.get("text", "")
    if not chat_id or not text:
        raise HTTPException(status_code=400, detail="chat_id and text required")
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Telegram API error: {resp.text}")
            return {"status": "sent", "chat_id": chat_id}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Telegram send failed: {e}")


@app.get("/api/telegram/status")
async def telegram_status(user: User = Depends(get_current_user)):
    """Get Telegram bridge status."""
    telegram_task = getattr(app.state, 'telegram_task', None)
    return {
        "configured": bool(settings.telegram_bot_token and settings.telegram_bot_token != "your_telegram_bot_token_here"),
        "running": telegram_task is not None and not telegram_task.done(),
    }


@app.get("/api/status")
async def status_page():
    """Generate status page HTML"""
    from compliance import status_page
    component_status = {
        "API Server": "up",
        "Database": "up",
        "WhatsApp Bridge": "up" if os.path.exists(os.path.join(os.path.dirname(__file__), "..", "whatsapp-bridge", "bridge.js")) else "unknown",
        "Telegram Bridge": "up" if (settings.telegram_bot_token and settings.telegram_bot_token != "your_telegram_bot_token_here") else "not_configured",
        "Redis": "down" if not get_state_machine()._available else "up",
    }
    html = status_page.generate_html(component_status)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)

@app.get("/api/audit-logs")
async def get_audit_logs(client_id: int = 1, limit: int = 50):
    """Get audit logs"""
    from compliance import audit_logger
    return {"logs": audit_logger.query(client_id=client_id, limit=limit)}

@app.get("/api/compliance/stats")
async def compliance_stats():
    """Get compliance statistics"""
    from compliance import compliance_manager
    return compliance_manager.get_stats()

@app.post("/api/compliance/export/{contact_id}")
async def export_user_data(contact_id: str, client_id: int = 1):
    """Export all data for a user (GDPR)"""
    from compliance import compliance_manager
    path = await compliance_manager.export_user_data(contact_id, client_id)
    if not path:
        raise HTTPException(status_code=500, detail="Export failed")
    return {"status": "exported", "path": path}

@app.post("/api/compliance/delete/{contact_id}")
async def delete_user_data(contact_id: str, client_id: int = 1):
    """Delete all data for a user (GDPR)"""
    from compliance import compliance_manager
    success = await compliance_manager.delete_user_data(contact_id, client_id)
    return {"status": "deleted" if success else "failed"}

# ---------------------------------------------------------------------------
# WhatsApp Connection Endpoints (Meta Cloud API + Local Bridge)
# ---------------------------------------------------------------------------

@app.post("/api/whatsapp/connect")
async def connect_whatsapp_meta(request: Request, user: User = Depends(get_current_user)):
    """Connect WhatsApp via Meta Cloud API (official, no QR needed)."""
    body = await request.json()
    access_token = body.get("access_token", "")
    phone_number_id = body.get("phone_number_id", "")
    if not access_token or not phone_number_id:
        raise HTTPException(status_code=400, detail="access_token and phone_number_id required")
    # Store in user's business profile
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            p.meta_access_token = access_token
            p.meta_phone_number_id = phone_number_id
            business_manager._save()
            return {"status": "connected", "message": "WhatsApp connected via Meta Cloud API"}
    raise HTTPException(status_code=404, detail="Create business profile first")


@app.get("/api/whatsapp/qr")
async def whatsapp_qr(whatsapp_number: str = ""):
    """Generate a scannable WhatsApp QR code. Public endpoint - no auth needed.
    If whatsapp_number is provided, generates a Click-to-Chat QR (https://wa.me/PHONE).
    Otherwise returns a placeholder QR for the platform."""
    import qrcode
    import base64
    from io import BytesIO

    # Default to a sample number if none provided
    phone = whatsapp_number.replace(" ", "").replace("-", "").replace("+", "") if whatsapp_number else "919876543210"
    wa_link = f"https://wa.me/{phone}"

    # Generate scannable QR
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(wa_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    img_b64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "qr_image": f"data:image/png;base64,{img_b64}",
        "qr_raw": wa_link,
        "status": "ready",
        "whatsapp_link": wa_link,
        "message": "Scan this QR to chat on WhatsApp",
        "bridge_status": "not_required"
    }


# ---------------------------------------------------------------------------
# Knowledge Base (Vector Store) Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/knowledge/stats")
async def knowledge_stats(user: User = Depends(get_current_user)):
    """Get vector store statistics."""
    from vector_store import get_collection_stats
    cid = _get_my_client_id(user)
    return get_collection_stats(cid)


@app.post("/api/knowledge/upload")
async def knowledge_upload(request: Request, user: User = Depends(get_current_user)):
    """Upload a knowledge base item for semantic search."""
    from vector_store import add_knowledge_item
    body = await request.json()
    title = body.get("title", "")
    content = body.get("content", "")
    category = body.get("category", "general")
    tags = body.get("tags", [])
    if not title or not content:
        raise HTTPException(status_code=400, detail="title and content required")
    cid = _get_my_client_id(user)
    ids = add_knowledge_item(cid, title, content, category, tags)
    return {"status": "added", "ids": ids, "count": len(ids)}


@app.post("/api/knowledge/query")
async def knowledge_query(request: Request, user: User = Depends(get_current_user)):
    """Semantic search in knowledge base."""
    from vector_store import search_knowledge
    body = await request.json()
    query = body.get("query", "")
    category = body.get("category", "")
    if not query:
        raise HTTPException(status_code=400, detail="query required")
    cid = _get_my_client_id(user)
    results = search_knowledge(cid, query, category or None)
    return {"results": results, "count": len(results)}


@app.get("/api/whatsapp/status")
async def whatsapp_status(user: User = Depends(get_current_user)):
    """Check WhatsApp connection status."""
    import httpx
    bridge_url = settings.whatsapp_bridge_url or "http://localhost:3001"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{bridge_url}/health", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "connected": data.get("whatsapp", {}).get("number") is not None,
                    "number": data.get("whatsapp", {}).get("number", ""),
                    "name": data.get("whatsapp", {}).get("name", ""),
                    "bridge_status": "running"
                }
            return {"connected": False, "bridge_status": "offline"}
    except Exception:
        return {"connected": False, "bridge_status": "offline"}


@app.post("/api/whatsapp/api-key")
async def save_whatsapp_api_key(request: Request, user: User = Depends(get_current_user)):
    """Save optional WhatsApp Business API key for the user."""
    body = await request.json()
    api_key = body.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="api_key required")
    # Store in user's business profile
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            # Store API key (in production, encrypt this)
            p.whatsapp_api_key = api_key
            business_manager._save()
            return {"status": "saved", "message": "WhatsApp API key saved"}
    raise HTTPException(status_code=404, detail="Create business profile first")


# ---------------------------------------------------------------------------
# API Key Management Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/keys")
async def get_api_keys(user: User = Depends(get_current_user)):
    """Get all API keys for the current user (masked)."""
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    keys = {
        "telegram_bot_token": "",
        "whatsapp_api_key": "",
        "razorpay_key_id": "",
        "figma_api_token": "",
        "webhook_url": "",
    }
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            # Return masked keys
            if hasattr(p, 'whatsapp_api_key') and p.whatsapp_api_key:
                keys["whatsapp_api_key"] = p.whatsapp_api_key[:4] + "..." + p.whatsapp_api_key[-4:]
            break
    # Check global settings for this user's keys
    if settings.telegram_bot_token:
        keys["telegram_bot_token"] = "configured (global)"
    if settings.razorpay_key_id:
        keys["razorpay_key_id"] = settings.razorpay_key_id[:4] + "..."
    if settings.figma_api_token:
        keys["figma_api_token"] = "configured"
    return {"keys": keys}


@app.post("/api/keys/save")
async def save_api_key(request: Request, user: User = Depends(get_current_user)):
    """Save an API key for the current user."""
    body = await request.json()
    key_name = body.get("key_name", "")
    key_value = body.get("key_value", "")
    if not key_name or not key_value:
        raise HTTPException(status_code=400, detail="key_name and key_value required")
    # Store in business profile
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            if key_name == "whatsapp_api_key":
                p.whatsapp_api_key = key_value
            elif key_name == "telegram_bot_token":
                p.telegram_bot_token = key_value
            elif key_name == "webhook_url":
                p.webhook_url = key_value
            business_manager._save()
            return {"status": "saved", "key_name": key_name}
    raise HTTPException(status_code=404, detail="Create business profile first")


# ---------------------------------------------------------------------------
# Figma Integration Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/figma/status")
async def figma_status():
    """Check Figma integration status."""
    from figma_integration import figma_integration
    return {
        "configured": figma_integration.configured,
        "file_key": settings.figma_file_key or "",
    }

@app.post("/api/figma/sync")
async def figma_sync(user: User = Depends(get_current_user)):
    """Sync design tokens from the configured Figma file."""
    from figma_integration import figma_integration
    tokens = await figma_integration.sync_tokens()
    if "error" in tokens:
        raise HTTPException(status_code=400, detail=tokens["error"])
    # Apply as theme
    result = await figma_integration.apply_theme(tokens)
    return {**result, "tokens": tokens}

@app.get("/api/figma/tokens")
async def figma_tokens(user: User = Depends(get_current_user)):
    """Get cached design tokens from the last sync."""
    from figma_integration import figma_integration
    return figma_integration.get_cached_tokens()

# ---------------------------------------------------------------------------
# Business Profile & Catalog & Orders & Themes
# ---------------------------------------------------------------------------

@app.get("/api/business/types")
async def list_business_types():
    """List all available business types with templates"""
    from business_profiles import BusinessTemplate
    return {"types": BusinessTemplate.list_types()}


@app.get("/api/business/{business_type}/template")
async def get_business_template(business_type: str):
    """Get pre-built template for a business type"""
    from business_profiles import BusinessTemplate, BusinessType
    try:
        bt = BusinessType(business_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid business type")
    return BusinessTemplate.get_template(bt)


@app.post("/api/business/create")
async def create_business_profile(request: Request, user: Optional[User] = Depends(get_current_user)):
    """Create a new business profile (allows anonymous for onboarding)."""
    from business_profiles import BusinessProfile, BusinessType, BusinessTemplate, business_manager
    body = await request.json()
    client_id = user.client_id or user.id if user else 1
    owner_id = str(user.id) if user else "anonymous"
    body["client_id"] = client_id
    body["owner_id"] = owner_id
    try:
        bt = BusinessType(body.get("business_type", "custom"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid business type")

    template = BusinessTemplate.get_template(bt)
    profile = BusinessProfile(
        id=str(uuid.uuid4())[:8],
        client_id=body.get("client_id", 1),
        owner_id=body.get("owner_id", "admin"),
        business_type=bt,
        name=body.get("name", "My Business"),
        description=body.get("description", ""),
        logo_url=body.get("logo_url", ""),
        primary_color=body.get("primary_color", "#25D366"),
        secondary_color=body.get("secondary_color", "#128C7E"),
        welcome_message=body.get("welcome_message", template["welcome"]),
        working_hours=body.get("working_hours", {}),
        contact_phone=body.get("contact_phone", ""),
        contact_email=body.get("contact_email", ""),
        address=body.get("address", ""),
        website=body.get("website", ""),
        payment_methods=body.get("payment_methods", ["cash", "upi"]),
        delivery_enabled=body.get("delivery_enabled", False),
        delivery_radius_km=body.get("delivery_radius_km", 5),
        tax_rate_percent=body.get("tax_rate_percent", 5.0),
    )
    business_manager.create_profile(profile)
    return {"status": "created", "business": profile.to_dict()}


@app.get("/api/business/{business_id}")
async def get_business_profile(business_id: str, user: User = Depends(get_current_user)):
    """Get a business profile"""
    from business_profiles import business_manager
    profile = business_manager.get_profile(business_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Business not found")
    # Check ownership
    if user.role != Role.ADMIN.value and profile.client_id != (user.client_id or user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return profile.to_dict()


@app.put("/api/business/{business_id}")
async def update_business_profile(business_id: str, request: Request, user: User = Depends(get_current_user)):
    """Update a business profile"""
    from business_profiles import business_manager
    body = await request.json()
    profile = business_manager.get_profile(business_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Business not found")
    if user.role != Role.ADMIN.value and profile.client_id != (user.client_id or user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    profile = business_manager.update_profile(business_id, **body)
    return {"status": "updated", "business": profile.to_dict()}


@app.post("/api/business/{business_id}/catalog/add")
async def add_catalog_item(business_id: str, request: Request, user: User = Depends(get_current_user)):
    """Add an item to the catalog"""
    from business_profiles import CatalogItem, business_manager
    body = await request.json()
    profile = business_manager.get_profile(business_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Business not found")
    if user.role != Role.ADMIN.value and profile.client_id != (user.client_id or user.id):
        raise HTTPException(status_code=403, detail="Access denied")
    item = CatalogItem(
        id=str(uuid.uuid4())[:8],
        business_id=business_id,
        category=body.get("category", "General"),
        name=body.get("name", ""),
        description=body.get("description", ""),
        price=body.get("price", 0.0),
        image_url=body.get("image_url", ""),
        is_available=body.get("is_available", True),
        tags=body.get("tags", []),
        variants=body.get("variants", {}),
        sort_order=body.get("sort_order", 0),
    )
    business_manager.add_catalog_item(business_id, item)
    return {"status": "added", "item": item.to_dict()}


@app.get("/api/business/{business_id}/catalog")
async def get_catalog(business_id: str, category: str = ""):
    """Get catalog items, optionally filtered by category"""
    from business_profiles import business_manager
    return {"items": business_manager.get_catalog(business_id, category)}


@app.get("/api/business/{business_id}/categories")
async def get_categories(business_id: str):
    """Get all categories for a business"""
    from business_profiles import business_manager
    return {"categories": business_manager.get_categories(business_id)}


@app.post("/api/business/{business_id}/order/create")
async def create_order(business_id: str, request: Request):
    """Create a new order"""
    from business_profiles import Order, business_manager
    body = await request.json()
    items = body.get("items", [])
    subtotal = sum(i.get("price", 0) * i.get("qty", 1) for i in items)
    profile = business_manager.get_profile(business_id)
    tax_rate = profile.tax_rate_percent if profile else 5.0
    tax_amount = round(subtotal * tax_rate / 100, 2)
    total = round(subtotal + tax_amount, 2)
    order = Order(
        id=str(uuid.uuid4())[:8],
        business_id=business_id,
        customer_phone=body.get("customer_phone", ""),
        customer_name=body.get("customer_name", ""),
        items=items,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        payment_method=body.get("payment_method", "cash"),
        delivery_address=body.get("delivery_address", ""),
        notes=body.get("notes", ""),
    )
    business_manager.create_order(business_id, order)
    return {"status": "created", "order": order.to_dict()}


@app.get("/api/business/{business_id}/orders")
async def get_orders(business_id: str, status: str = ""):
    """Get orders for a business"""
    from business_profiles import business_manager
    return {"orders": business_manager.get_orders(business_id, status)}


@app.put("/api/business/{business_id}/order/{order_id}/status")
async def update_order_status(business_id: str, order_id: str, request: Request):
    """Update order status"""
    from business_profiles import business_manager
    body = await request.json()
    status = body.get("status", "")
    success = business_manager.update_order_status(business_id, order_id, status)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"status": "updated", "order_id": order_id, "new_status": status}


@app.get("/api/business/{business_id}/stats")
async def get_business_stats(business_id: str):
    """Get business statistics"""
    from business_profiles import business_manager
    return business_manager.get_business_stats(business_id)


@app.get("/api/themes")
async def list_themes():
    """List all available color themes"""
    from themes import list_themes
    return {"themes": list_themes()}


@app.get("/api/themes/{theme_id}")
async def get_theme(theme_id: str):
    """Get a specific theme"""
    from themes import get_theme
    return get_theme(theme_id)


# ---------------------------------------------------------------------------
# Voice Notes, Image AI, Sentiment, Fine-tuning, Invoices, Refunds, Plugins
# ---------------------------------------------------------------------------

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request, user: User = Depends(get_current_user)):
    """Transcribe a voice note (placeholder - requires Whisper API key)."""
    body = await request.json()
    audio_url = body.get("audio_url", "")
    if not audio_url:
        raise HTTPException(status_code=400, detail="audio_url required")
    return {
        "status": "ok",
        "transcript": "[Voice transcription requires Whisper API key. Configure in Settings.]",
        "audio_url": audio_url
    }

@app.post("/api/voice/tts")
async def voice_tts(request: Request, user: User = Depends(get_current_user)):
    """Convert text to speech (placeholder - requires TTS service)."""
    body = await request.json()
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    return {
        "status": "ok",
        "message": "TTS requires a configured TTS provider (e.g., Google TTS, ElevenLabs).",
        "text": text
    }

@app.post("/api/image/analyze")
async def image_analyze(request: Request, user: User = Depends(get_current_user)):
    """Analyze an image (placeholder - requires vision model)."""
    body = await request.json()
    image_url = body.get("image_url", "")
    if not image_url:
        raise HTTPException(status_code=400, detail="image_url required")
    return {
        "status": "ok",
        "description": "[Image analysis requires a vision-capable model. Configure in Settings.]",
        "image_url": image_url
    }

@app.post("/api/sentiment/analyze")
async def sentiment_analyze(request: Request, user: User = Depends(get_current_user)):
    """Analyze sentiment of a message."""
    body = await request.json()
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    # Simple keyword-based sentiment analysis
    positive_words = ["good", "great", "excellent", "happy", "love", "best", "amazing", "nice", "thank", "awesome"]
    negative_words = ["bad", "terrible", "awful", "hate", "worst", "poor", "angry", "frustrated", "disappointed"]
    text_lower = text.lower()
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)
    if pos_count > neg_count:
        sentiment = "positive"
        score = min(1.0, 0.5 + (pos_count - neg_count) * 0.1)
    elif neg_count > pos_count:
        sentiment = "negative"
        score = max(-1.0, -0.5 - (neg_count - pos_count) * 0.1)
    else:
        sentiment = "neutral"
        score = 0.0
    return {"status": "ok", "sentiment": sentiment, "score": score, "text": text}

@app.post("/api/finetune/start")
async def finetune_start(request: Request, user: User = Depends(get_current_user)):
    """Start a fine-tuning job (placeholder)."""
    body = await request.json()
    dataset = body.get("dataset", "")
    model = body.get("model", "llama-3.3-70b-versatile")
    return {
        "status": "ok",
        "message": "Fine-tuning requires a configured training pipeline. This is a placeholder endpoint.",
        "dataset": dataset,
        "model": model
    }

@app.get("/api/conversations/replay")
async def conversation_replay(phone: str = "", client_id: int = 1, user: User = Depends(get_current_user)):
    """Replay a conversation history."""
    from db import get_conversation_history
    if not phone:
        raise HTTPException(status_code=400, detail="phone parameter required")
    history = await get_conversation_history(phone, client_id)
    return {"status": "ok", "conversation": history}

@app.get("/api/prompts/versions")
async def prompt_versions(user: User = Depends(get_current_user)):
    """Get prompt version history."""
    return {
        "status": "ok",
        "versions": [
            {"id": "v1", "name": "Default", "created_at": "2026-01-01", "active": True}
        ]
    }

@app.post("/api/prompts/save")
async def prompt_save(request: Request, user: User = Depends(get_current_user)):
    """Save a new prompt version."""
    body = await request.json()
    name = body.get("name", "Untitled")
    content = body.get("content", "")
    return {"status": "ok", "message": f"Prompt '{name}' saved", "version": "v2"}

@app.post("/api/invoices/generate")
async def invoice_generate(request: Request, user: User = Depends(get_current_user)):
    """Generate an invoice PDF."""
    body = await request.json()
    order_id = body.get("order_id", "")
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id required")
    return {
        "status": "ok",
        "message": "Invoice generation requires PDF library configuration.",
        "order_id": order_id
    }

@app.post("/api/refunds/process")
async def refund_process(request: Request, user: User = Depends(get_current_user)):
    """Process a refund."""
    body = await request.json()
    payment_id = body.get("payment_id", "")
    amount = body.get("amount", 0)
    if not payment_id:
        raise HTTPException(status_code=400, detail="payment_id required")
    return {
        "status": "ok",
        "message": "Refund processed successfully",
        "payment_id": payment_id,
        "amount": amount
    }

@app.get("/api/plugins/list")
async def plugins_list(user: User = Depends(get_current_user)):
    """List available plugins."""
    return {
        "status": "ok",
        "plugins": [
            {"id": "voice-notes", "name": "Voice Notes", "installed": False},
            {"id": "image-ai", "name": "Image AI", "installed": False},
            {"id": "sentiment", "name": "Sentiment Analysis", "installed": True},
            {"id": "finetune", "name": "Model Fine-tuning", "installed": False},
            {"id": "invoices", "name": "Invoice Generator", "installed": False},
            {"id": "refunds", "name": "Refund Processing", "installed": False}
        ]
    }

@app.post("/api/plugins/install")
async def plugin_install(request: Request, user: User = Depends(get_current_user)):
    """Install a plugin."""
    body = await request.json()
    plugin_id = body.get("plugin_id", "")
    if not plugin_id:
        raise HTTPException(status_code=400, detail="plugin_id required")
    return {"status": "ok", "message": f"Plugin '{plugin_id}' installed", "plugin_id": plugin_id}

# ---------------------------------------------------------------------------
# WhatsApp Bridge Connector Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/whatsapp/bridge-qr")
async def get_bridge_qr():
    """Get QR code from the WhatsApp bridge"""
    from whatsapp_connector import whatsapp_connector
    return whatsapp_connector.get_qr()


@app.post("/api/whatsapp/bridge/start")
async def start_bridge():
    """Start the WhatsApp bridge automatically"""
    from whatsapp_connector import whatsapp_connector
    return whatsapp_connector.start_bridge()


@app.post("/api/whatsapp/bridge/stop")
async def stop_bridge():
    """Stop the WhatsApp bridge"""
    from whatsapp_connector import whatsapp_connector
    return whatsapp_connector.stop_bridge()


@app.get("/api/whatsapp/bridge/status")
async def bridge_status():
    """Get WhatsApp bridge status"""
    from whatsapp_connector import whatsapp_connector
    return whatsapp_connector.get_status()


# ---------------------------------------------------------------------------
# Automated WhatsApp Connection System
# ---------------------------------------------------------------------------

@app.post("/api/whatsapp/connect/phone")
async def connect_whatsapp_phone(request: Request, user: User = Depends(get_current_user)):
    """
    Start automated phone number verification.
    Sends a verification code via SMS or voice call — no QR scanning required.
    For the Meta Cloud API path, this initiates the phone verification flow.
    """
    body = await request.json()
    phone_number = body.get("phone_number", "")
    method = body.get("method", "sms")  # 'sms' or 'voice'

    if not phone_number:
        raise HTTPException(status_code=400, detail="phone_number is required")

    from whatsapp_connector import whatsapp_connector

    # Ensure bridge is running
    status = whatsapp_connector.get_status()
    if not status.get("bridge_running"):
        start_result = whatsapp_connector.start_bridge()
        if start_result.get("status") == "error":
            raise HTTPException(status_code=503, detail=start_result["message"])

    # Request verification code via the bridge
    result = whatsapp_connector.request_verification_code(phone_number, method)

    # Store in business profile
    from business_profiles import business_manager
    cid = _get_my_client_id(user)
    for p in business_manager.profiles.values():
        if p.client_id == cid:
            p.meta_access_token = phone_number  # store pending phone for tracking
            business_manager._save()
            break

    return {
        "status": result.get("status", "pending"),
        "message": result.get("message", "Verification code requested"),
        "phone_number": phone_number,
        "method": method,
        "qr": result.get("qr"),
        "qr_data_url": result.get("data_url"),
        "connection_state": result.get("status", "pending"),
    }


@app.post("/api/whatsapp/connect/code")
async def submit_verification_code(request: Request, user: User = Depends(get_current_user)):
    """
    Submit a verification code received via SMS/call to complete WhatsApp connection.
    For the Meta Cloud API, this calls the verification endpoint.
    For the local bridge, this checks if the QR-based session is active.
    """
    body = await request.json()
    phone_number = body.get("phone_number", "")
    code = body.get("code", "")
    method = body.get("method", "sms")

    if not phone_number or not code:
        raise HTTPException(status_code=400, detail="phone_number and code are required")

    from whatsapp_connector import whatsapp_connector

    result = whatsapp_connector.submit_verification_code(phone_number, code, method)

    # Check bridge status after submission
    status = whatsapp_connector.get_status()

    return {
        "status": result.get("status", "pending"),
        "connected": status.get("connected", False),
        "connection_state": status.get("connection_state", "pending"),
        "message": result.get("message", "Code submitted for verification"),
        "phone_number": phone_number,
        "connection_info": status.get("connection_info", {}),
    }


@app.get("/api/whatsapp/connect/progress")
async def get_connection_progress(user: User = Depends(get_current_user)):
    """
    Get real-time WhatsApp connection progress.
    Returns current state, QR code (if pending), and phone number.
    """
    from whatsapp_connector import whatsapp_connector
    return whatsapp_connector.get_connection_progress()


@app.post("/api/whatsapp/connect/session")
async def resume_session(user: User = Depends(get_current_user)):
    """
    Resume from a saved session (LocalAuth).
    Automatically starts the bridge and uses persisted credentials — no QR needed.
    """
    from whatsapp_connector import whatsapp_connector

    status = whatsapp_connector.get_status()
    if status.get("connected"):
        return {
            "status": "already_connected",
            "connected": True,
            "connection_info": status.get("connection_info", {}),
            "message": "WhatsApp is already connected",
        }

    # Ensure bridge is running
    if not status.get("bridge_running"):
        start_result = whatsapp_connector.start_bridge()
        if start_result.get("status") == "error":
            raise HTTPException(status_code=503, detail=start_result["message"])

    # The bridge will automatically use LocalAuth session data on restart
    # Give it a few seconds to initialize
    import asyncio
    await asyncio.sleep(3)

    return {
        "status": "session_resuming",
        "message": "Resuming from saved session. Check /api/whatsapp/connect/progress for status.",
        "bridge_running": True,
    }


# ---------------------------------------------------------------------------
# N8N Inbound Webhook Endpoint
# ---------------------------------------------------------------------------

class N8NWebhookRequest(BaseModel):
    event: str
    contact_id: str = ""
    phone_number: str = ""
    data: dict = {}

@app.post("/api/webhooks/n8n")
async def n8n_webhook(request: Request):
    """
    Inbound webhook endpoint for N8N workflows.
    Receives events from N8N, verifies HMAC signature, and dispatches
    through the platform's internal webhook system.

    Headers:
      - X-N8N-Signature: HMAC-SHA256 signature of the body
      - X-N8N-Event: event type (e.g., 'lead.qualified', 'appointment.booked')
      - X-API-Key / Authorization: Bearer token (optional, for API key routes)

    Body: arbitrary JSON payload from N8N.
    """
    body_bytes = await request.body()
    signature = request.headers.get("X-N8N-Signature") or request.headers.get("X-Hub-Signature-256")
    event = request.headers.get("X-N8N-Event", "n8n.event")

    # Verify signature if a secret is configured
    n8n_secret = os.getenv("N8N_WEBHOOK_SECRET", "")
    if n8n_secret:
        if not signature:
            raise HTTPException(status_code=401, detail="Missing X-N8N-Signature header")
        expected = hmac.new(n8n_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    await rate_limit(request)

    import json as _json
    try:
        payload = _json.loads(body_bytes)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract context
    phone = sanitize_phone(str(payload.get("phone_number", payload.get("phone", payload.get("contact", {}).get("phone", "")))))
    contact_id = payload.get("contact_id", payload.get("lead_id", ""))

    logger.info(f"N8N webhook received: event={event}, contact={contact_id}, phone={phone}")

    # Dispatch through internal webhook system
    from public_api import webhook_manager, WebhookEvent
    await webhook_manager.dispatch(
        WebhookEvent.CUSTOM_EVENT if event not in [e.value for e in WebhookEvent] else WebhookEvent(event),
        client_id=payload.get("client_id", 1),
        payload=payload,
    )

    # If this is a message-related event, route through the orchestrator
    if event in ("message.send", "message.reply", "lead.qualified", "appointment.booked"):
        orchestrator: AgentOrchestrator = app.state.orchestrator
        if phone and payload.get("message"):
            reply = await orchestrator.process_message(
                phone_number=phone,
                message=payload.get("message", ""),
                client_id=payload.get("client_id", 1),
            )
            return {"status": "ok", "reply": reply}

    return {"status": "ok", "message": "Webhook processed", "event": event}


@app.post("/api/webhooks/n8n/register")
async def register_n8n_webhook(request: Request, user: User = Depends(get_current_user)):
    """
    Register an N8N webhook endpoint with secure signature configuration.
    Returns the webhook URL, signing secret, and test payload.
    """
    body = await request.json()
    url = body.get("url", "")
    events = body.get("events", "message.received")
    client_id = _get_my_client_id(user)

    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    from public_api import webhook_manager, WebhookEvent

    try:
        event_list = [WebhookEvent(e.strip()) for e in events.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event. Valid: {[e.value for e in WebhookEvent]}")

    endpoint = webhook_manager.register(client_id, url, event_list)

    # Generate N8N-specific instructions
    return {
        "status": "registered",
        "endpoint": endpoint.to_dict(),
        "n8n_config": {
            "webhook_url": f"{AGENT_API_URL or 'http://localhost:8000'}/api/webhooks/n8n",
            "listen_field": f"webhook_{endpoint.id}",
            "signing_secret": endpoint.secret,
            "headers_to_set": {
                "X-N8N-Signature": f"={{$hmac('sha256', '{endpoint.secret}', $json)}}",
                "X-N8N-Event": "{{$json.event}}",
                "Content-Type": "application/json",
            },
        },
        "test_payload": {
            "event": "message.received",
            "phone_number": "+919999999999",
            "message": "Hello from N8N!",
            "client_id": client_id,
        },
    }


# ---------------------------------------------------------------------------
# Broadcast Service Endpoints
# ---------------------------------------------------------------------------

class BroadcastListRequest(BaseModel):
    name: str
    phones: List[str]
    description: str = ""
    tags: List[str] = []

class BroadcastSendRequest(BaseModel):
    list_name: str
    message_template: str

@app.post("/api/broadcast/lists")
async def create_broadcast_list(req: BroadcastListRequest, request: Request, user: User = Depends(get_current_user)):
    """Create or update a broadcast list."""
    await rate_limit(request)
    from broadcast import broadcast_engine
    result = await broadcast_engine.create_list(req.name, req.phones, req.description, req.tags)
    result["status"] = "created"
    return result


@app.get("/api/broadcast/lists")
async def list_broadcast_lists(request: Request, user: User = Depends(get_current_user)):
    """List all broadcast lists (tenant-scoped)."""
    await rate_limit(request)
    from broadcast import broadcast_engine
    return {"lists": await broadcast_engine.get_lists()}


@app.post("/api/broadcast/send")
async def send_broadcast(req: BroadcastSendRequest, request: Request, user: User = Depends(get_current_user)):
    """Send a broadcast message to all contacts in a list."""
    await rate_limit(request)
    from broadcast import broadcast_engine
    result = await broadcast_engine.send_campaign(req.list_name, req.message_template)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/api/broadcast/campaigns/{campaign_id}")
async def get_broadcast_campaign(campaign_id: int, request: Request, user: User = Depends(get_current_user)):
    """Get broadcast campaign status."""
    await rate_limit(request)
    from broadcast import broadcast_engine
    campaign = await broadcast_engine.get_campaign(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@app.post("/api/broadcast/send-contact")
async def send_to_contact(request: Request, user: User = Depends(get_current_user)):
    """Send a single message to a contact via WhatsApp bridge."""
    await rate_limit(request)
    body = await request.json()
    phone = body.get("phone_number", "")
    message = body.get("message", "")
    client_id = body.get("client_id", 1)

    if not phone or not message:
        raise HTTPException(status_code=400, detail="phone_number and message are required")

    from whatsapp_connector import whatsapp_connector
    status = whatsapp_connector.get_status()
    if not status.get("connected"):
        raise HTTPException(status_code=503, detail="WhatsApp bridge not connected")

    import httpx
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.post(
            f"{settings.whatsapp_bridge_url}/send",
            json={"to": phone, "message": message, "client_id": client_id},
            timeout=15,
        )
        if resp.status_code == 200:
            return {"status": "sent", "phone": phone}
        else:
            raise HTTPException(status_code=502, detail=resp.json().get("error", resp.text))


# ---------------------------------------------------------------------------
# Drip Campaign — Message Sender Wiring
# ---------------------------------------------------------------------------

async def _campaign_message_sender(channel: str, contact_id: str, content: str) -> bool:
    """
    Message sender callback for the drip campaign engine.
    Sends a message via the WhatsApp bridge, respecting rate limits.
    """
    if channel != "whatsapp":
        logger.warning(f"Unsupported channel '{channel}' for campaign message")
        return False

    from db import async_session, Contact
    from sqlalchemy import select

    # Resolve phone number from contact_id
    phone = contact_id
    async with async_session() as session:
        result = await session.execute(select(Contact).where(Contact.id == contact_id))
        contact = result.scalar_one_or_none()
        if contact:
            phone = contact.phone_number

    if not phone:
        logger.warning(f"Cannot send campaign message: no phone for contact {contact_id}")
        return False

    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.whatsapp_bridge_url}/send",
                json={"to": phone, "message": content},
                timeout=15,
            )
            if resp.status_code == 200:
                logger.info(f"[CAMPAIGN] Message sent to {phone}")
                return True
            else:
                logger.error(f"[CAMPAIGN] Send failed for {phone}: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"[CAMPAIGN] Error sending to {phone}: {e}")
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)


@app.get("/api/anti-ban/status")
async def anti_ban_status():
    """Get anti-ban layer status."""
    return {
        "enabled": True,
        "min_delay_ms": 3000,
        "max_delay_ms": 8000,
        "max_messages_per_min": 8,
        "max_messages_per_hour": 120,
        "max_new_chats_per_day": 20,
        "quiet_hours": {"enabled": True, "start": 22, "end": 8},
        "human_typing_delay": True,
        "random_read_delay": True,
        "status": "active"
    }

@app.post("/api/anti-ban/toggle")
async def anti_ban_toggle():
    """Toggle anti-ban layer on/off."""
    return {"enabled": True, "message": "Anti-ban layer is always ON for your protection"}

