import hashlib
import hmac
import base64
from datetime import datetime, timedelta
import httpx
from config import settings


class AmazonSPClient:
    def __init__(self, client_id: str = None, client_secret: str = None, refresh_token: str = None):
        self.base_url = settings.amazon_sp_api_url or "https://sellingpartnerapi-na.amazon.com"
        self.client_id = client_id or settings.amazon_client_id
        self.client_secret = client_secret or settings.amazon_client_secret
        self.refresh_token = refresh_token or settings.amazon_refresh_token
        self._access_token = None
        self._token_expires_at = None

    async def _get_token(self) -> str:
        if self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.amazon.com/auth/o2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            return self._access_token

    async def _request(self, method: str, endpoint: str, **kwargs):
        token = await self._get_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient() as client:
            resp = await client.request(method, f"{self.base_url}{endpoint}", headers=headers, **kwargs)
            resp.raise_for_status()
            return resp.json()

    async def test_connection(self) -> dict:
        try:
            if not self.client_id or not self.client_secret or not self.refresh_token:
                return {"connected": False, "error": "Missing credentials"}
            token = await self._get_token()
            return {"connected": True, "token_preview": token[:10] + "..."}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def fetch_orders(self, created_after: str = None, limit: int = 100) -> dict:
        endpoint = f"/orders/v0/orders?MarketplaceIds=ATVPDKIKX0DER&MaxResultsPerPage={limit}"
        if created_after:
            endpoint += f"&CreatedAfter={created_after}"
        return await self._request("GET", endpoint)

    async def fetch_listings(self, sku: str = "") -> dict:
        if sku:
            endpoint = f"/listings/v1/items/{sku}"
        else:
            endpoint = "/listings/v1/items"
        return await self._request("GET", endpoint)

    async def update_listing(self, sku: str, data: dict) -> dict:
        endpoint = f"/listings/v1/items/{sku}"
        return await self._request("PUT", endpoint, json=data)

    async def fetch_inventory(self, sku: str) -> dict:
        endpoint = f"/inventory/v1/summaries/MarketplaceId=ATVPDKIKX0DER/Sku={sku}"
        return await self._request("GET", endpoint)
