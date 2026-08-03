"""
Payment Integration — Razorpay payment links + UPI deep-links.
"""
import hashlib
import hmac
import urllib.parse
from typing import Optional

import httpx
from config import settings


class PaymentEngine:
    """Razorpay payment link creation, webhook verification, and UPI deep-links."""

    RAZORPAY_BASE = "https://api.razorpay.com/v1"

    def __init__(self):
        self.key_id = settings.razorpay_key_id
        self.key_secret = settings.razorpay_key_secret

    @property
    def _configured(self) -> bool:
        return bool(self.key_id and self.key_secret
                    and self.key_id != "your_razorpay_key_id"
                    and self.key_secret != "your_razorpay_key_secret")

    # -- Razorpay Payment Link ----------------------------------------------

    async def create_payment_link(self, amount: int, description: str,
                                  phone: str = "", name: str = "") -> dict:
        """
        Create a Razorpay payment link.
        amount: in paise (e.g., 50000 = ₹500)
        Returns: {"short_url": "https://rzp.io/...", "id": "plink_...", ...}
        """
        if not self._configured:
            return {"error": "Razorpay keys not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in .env"}

        payload = {
            "amount": amount,
            "currency": "INR",
            "description": description,
            "customer": {},
            "notify": {"sms": False, "email": False},
            "callback_method": "get",
        }
        if phone:
            payload["customer"]["contact"] = phone
        if name:
            payload["customer"]["name"] = name

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.RAZORPAY_BASE}/payment_links",
                json=payload,
                auth=(self.key_id, self.key_secret),
                timeout=15,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {
                    "id": data.get("id"),
                    "short_url": data.get("short_url"),
                    "amount": data.get("amount"),
                    "status": data.get("status"),
                }
            return {"error": resp.text, "status_code": resp.status_code}

    # -- Webhook Verification -----------------------------------------------

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        """Verify Razorpay webhook signature (HMAC-SHA256)."""
        if not self.key_secret:
            return False
        expected = hmac.new(
            self.key_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # -- Payment Status -----------------------------------------------------

    async def get_payment_status(self, payment_link_id: str) -> dict:
        """Check status of a Razorpay payment link."""
        if not self._configured:
            return {"error": "Razorpay keys not configured"}

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.RAZORPAY_BASE}/payment_links/{payment_link_id}",
                auth=(self.key_id, self.key_secret),
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "id": data.get("id"),
                    "status": data.get("status"),
                    "amount": data.get("amount"),
                    "amount_paid": data.get("amount_paid"),
                    "payments": data.get("payments"),
                }
            return {"error": resp.text, "status_code": resp.status_code}

    # -- UPI Deep-Link (no API needed) --------------------------------------

    @staticmethod
    def generate_upi_link(upi_id: str, amount: float,
                          payee_name: str = "", note: str = "") -> dict:
        """
        Generate a UPI deep-link. Works with any UPI app (GPay, PhonePe, Paytm).
        amount: in rupees (e.g., 500.00)
        """
        params = {
            "pa": upi_id,
            "am": f"{amount:.2f}",
            "cu": "INR",
        }
        if payee_name:
            params["pn"] = payee_name
        if note:
            params["tn"] = note

        upi_url = "upi://pay?" + urllib.parse.urlencode(params)
        return {"upi_url": upi_url, "amount": amount, "upi_id": upi_id}
