import httpx
from datetime import datetime, timedelta
from config import settings


class FlipkartSellerClient:
    def __init__(self, client_id: str = None, client_secret: str = None):
        self.base_url = settings.flipkart_api_url or "https://api.flipkart.net"
        self.client_id = client_id or settings.flipkart_client_id
        self.client_secret = client_secret or settings.flipkart_client_secret
        self._access_token = None
        self._token_expires_at = None

    async def _get_token(self) -> str:
        if self._access_token and self._token_expires_at and datetime.now() < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/oauth-service/oauth/token",
                data={
                    "grant_type": "client_credentials",
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
            if not self.client_id or not self.client_secret:
                return {"connected": False, "error": "Missing credentials"}
            token = await self._get_token()
            return {"connected": True, "token_preview": token[:10] + "..."}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def fetch_orders(self, page_size: int = 50, page: int = 1) -> dict:
        return await self._request("GET", f"/api/v2/orders/search?pageSize={page_size}&page={page}")

    async def fetch_listings(self, sku: str = "") -> dict:
        endpoint = f"/api/v2/listing/filter?sku={sku}" if sku else "/api/v2/listing/filter"
        return await self._request("GET", endpoint)

    async def update_listing(self, listing_id: str, data: dict) -> dict:
        return await self._request("PUT", f"/api/v2/listing/{listing_id}", json=data)

    async def fetch_shipments(self, order_id: str) -> dict:
        return await self._request("GET", f"/api/v2/shipments?orderId={order_id}")

    async def update_shipment_status(self, shipment_id: str, status: str) -> dict:
        return await self._request("PUT", f"/api/v2/shipment/{shipment_id}", json={"status": status})
