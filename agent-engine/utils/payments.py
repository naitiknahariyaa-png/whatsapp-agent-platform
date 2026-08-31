"""
Payments Functions
Turns a sales conversation into a completed transaction without leaving WhatsApp.
"""
import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# 7.1 generate_payment_link — WhatsApp-native payments
# =============================================================================
@dataclass
class PaymentLinkRequest:
    amount: float  # in smallest currency unit (paise for INR)
    currency: str = "INR"
    description: str = "Payment"
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    callback_url: Optional[str] = None
    expire_by: Optional[int] = None  # Unix timestamp
    notes: Optional[Dict[str, str]] = None


@dataclass
class PaymentLinkResponse:
    success: bool
    payment_link_id: Optional[str] = None
    short_url: Optional[str] = None
    long_url: Optional[str] = None
    amount: float = 0
    currency: str = "INR"
    status: str = "created"
    expires_at: Optional[datetime] = None
    error: Optional[str] = None


async def generate_payment_link(
    request: PaymentLinkRequest,
    provider: str = "razorpay",  # or "stripe"
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> PaymentLinkResponse:
    """
    Wraps Razorpay/Stripe link creation.
    Turns a sales conversation into a completed transaction without leaving WhatsApp.
    
    Args:
        request: PaymentLinkRequest with amount, currency, customer details
        provider: "razorpay" or "stripe"
        api_key: Provider API key
        api_secret: Provider API secret
    
    Returns:
        PaymentLinkResponse with short URL for WhatsApp
    """
    if provider == "razorpay":
        return await _generate_razorpay_link(request, api_key, api_secret)
    elif provider == "stripe":
        return await _generate_stripe_link(request, api_key)
    else:
        return PaymentLinkResponse(
            success=False,
            error=f"Unsupported provider: {provider}",
        )


async def _generate_razorpay_link(
    request: PaymentLinkRequest,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
) -> PaymentLinkResponse:
    """Generate Razorpay payment link."""
    import os
    
    api_key = api_key or os.getenv("RAZORPAY_KEY_ID")
    api_secret = api_secret or os.getenv("RAZORPAY_KEY_SECRET")
    
    if not api_key or not api_secret:
        return PaymentLinkResponse(success=False, error="Razorpay credentials not configured")
    
    payload = {
        "amount": int(request.amount),  # in paise
        "currency": request.currency,
        "description": request.description,
        "callback_url": request.callback_url,
        "callback_method": "get",
    }
    
    if request.customer_name:
        payload["customer"] = {"name": request.customer_name}
    if request.customer_email:
        payload.setdefault("customer", {})["email"] = request.customer_email
    if request.customer_phone:
        payload.setdefault("customer", {})["contact"] = request.customer_phone
    if request.expire_by:
        payload["expire_by"] = request.expire_by
    if request.notes:
        payload["notes"] = request.notes
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.razorpay.com/v1/payment_links",
            json=payload,
            auth=(api_key, api_secret),
        )
    
    if response.status_code in (200, 201):
        data = response.json()
        return PaymentLinkResponse(
            success=True,
            payment_link_id=data.get("id"),
            short_url=data.get("short_url"),
            long_url=data.get("short_url") or data.get("url"),
            amount=request.amount / 100,
            currency=request.currency,
            status=data.get("status", "created"),
            expires_at=datetime.fromtimestamp(data["expire_by"], tz=timezone.utc) if data.get("expire_by") else None,
        )
    else:
        logger.error(f"Razorpay link creation failed: {response.text}")
        return PaymentLinkResponse(
            success=False,
            error=f"Razorpay error: {response.text}",
        )


async def _generate_stripe_link(
    request: PaymentLinkRequest,
    api_key: Optional[str] = None,
) -> PaymentLinkResponse:
    """Generate Stripe payment link (placeholder)."""
    # Stripe implementation would go here
    return PaymentLinkResponse(
        success=False,
        error="Stripe integration not yet implemented",
    )


# =============================================================================
# 7.2 verify_payment_webhook — Security-critical validation
# =============================================================================
def verify_payment_webhook(
    payload: bytes,
    signature: str,
    provider: str = "razorpay",
    webhook_secret: Optional[str] = None,
) -> bool:
    """
    Validates the payment provider's webhook signature.
    Security-critical — an unverified payment webhook is a direct fraud vector.
    
    Args:
        payload: Raw request body
        signature: Signature header value
        provider: "razorpay" or "stripe"
        webhook_secret: Webhook signing secret
    
    Returns:
        True if signature is valid
    """
    if provider == "razorpay":
        secret = webhook_secret or os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
        if not secret:
            logger.warning("Razorpay webhook secret not configured")
            return False
        
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        
        # Razorpay sends signature as-is
        sig = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, sig)
    
    elif provider == "stripe":
        # Stripe uses a different format
        # Implementation would go here
        return False
    
    return False


# =============================================================================
# 7.3 on_payment_success — Closes the loop automatically
# =============================================================================
@dataclass
class PaymentSuccessData:
    payment_link_id: str
    payment_id: str
    amount: float
    currency: str
    customer_phone: Optional[str] = None
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    metadata: Dict[str, Any] = None


async def on_payment_success(
    data: PaymentSuccessData,
    db_session=None,
) -> bool:
    """
    Updates lead status, triggers receipt + confirmation message.
    Closes the loop automatically — no manual follow-up needed.
    
    Args:
        data: Payment success data from webhook
        db_session: Database session
    
    Returns:
        True if processed successfully
    """
    try:
        # Update lead status in DB
        if db_session:
            from db import Lead
            from sqlalchemy import select, update
            
            # Find lead by payment link ID or phone
            query = select(Lead).where(
                Lead.payment_link_id == data.payment_link_id
            )
            if data.customer_phone:
                query = query.where(Lead.phone == data.customer_phone)
            
            result = await db_session.execute(query)
            lead = result.scalar_one_or_none()
            
            if lead:
                lead.status = "converted"
                lead.payment_id = data.payment_id
                lead.payment_amount = data.amount
                lead.payment_currency = data.currency
                lead.payment_completed_at = datetime.now(timezone.utc)
                lead.updated_at = datetime.now(timezone.utc)
                await db_session.commit()
        
        # Send confirmation message
        if data.customer_phone:
            from outbound_limiter import send_whatsapp
            msg = (
                f"✅ Payment Received!\n\n"
                f"Amount: {data.currency} {data.amount:,.2f}\n"
                f"Payment ID: {data.payment_id}\n"
                f"Thank you for your payment! 🙏"
            )
            await send_whatsapp(data.customer_phone, msg)
        
        # Send receipt (email/WhatsApp)
        if data.customer_email:
            # Send email receipt
            pass
        
        # Update CRM/analytics
        await track_event("payment_completed", {
            "payment_link_id": data.payment_link_id,
            "payment_id": data.payment_id,
            "amount": data.amount,
            "currency": data.currency,
        })
        
        logger.info(f"Payment {data.payment_id} processed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Payment success handling failed: {e}")
        return False


# =============================================================================
# 7.4 retry_failed_payment_reminder — Recovers lost revenue
# =============================================================================
async def retry_failed_payment_reminder(
    payment_link_id: str,
    hours_since_creation: int = 24,
    max_reminders: int = 3,
    db_session=None,
) -> bool:
    """
    Sends a gentle nudge if a generated link goes unpaid after N hours.
    Recovers revenue that would otherwise silently drop.
    
    Args:
        payment_link_id: Payment link to check
        hours_since_creation: Hours after which to send reminder
        max_reminders: Max number of reminders to send
        db_session: Database session
    
    Returns:
        True if reminder sent, False otherwise
    """
    try:
        if not db_session:
            return False
        
        from db import PaymentLink, Lead
        from sqlalchemy import select, and_
        
        # Find payment link
        result = await db_session.execute(
            select(PaymentLink).where(PaymentLink.id == payment_link_id)
        )
        payment_link = result.scalar_one_or_none()
        
        if not payment_link:
            return False
        
        # Check if already paid
        if payment_link.status in ["paid", "completed"]:
            return False
        
        # Check if expired
        if payment_link.expires_at and datetime.now(timezone.utc) > payment_link.expires_at:
            payment_link.status = "expired"
            await db_session.commit()
            return False
        
        # Check reminder count
        if payment_link.reminder_count >= max_reminders:
            return False
        
        # Check time since creation
        created_at = payment_link.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        if datetime.now(timezone.utc) - created_at < timedelta(hours=hours_since_creation):
            return False
        
        # Send reminder
        if payment_link.customer_phone:
            from outbound_limiter import send_whatsapp
            msg = (
                f"💳 Payment Reminder\n\n"
                f"You have a pending payment of {payment_link.currency} {payment_link.amount/100:,.2f}\n"
                f"Link: {payment_link.short_url}\n\n"
                f"This link expires in {(payment_link.expires_at - datetime.now(timezone.utc)).days} days."
            )
            await send_whatsapp(payment_link.customer_phone, msg)
            
            # Increment reminder count
            payment_link.reminder_count += 1
            payment_link.last_reminder_at = datetime.now(timezone.utc)
            await db_session.commit()
            
            logger.info(f"Sent payment reminder for link {payment_link_id}")
            return True
        
    except Exception as e:
        logger.error(f"Payment reminder failed: {e}")
    
    return False


# =============================================================================
# Helper: Environment variable
# =============================================================================
import os