"""
Calendar client - talks to Cal.com over HTTP
"""
import httpx
from config import settings


class CalendarClient:
    """HTTP client for Cal.com calendar service"""

    def __init__(self, base_url: str = "http://calendar-service:3000"):
        self.base_url = base_url.rstrip("/")

    async def book_slot(self, date: str, time: str, phone_number: str, name: str = None) -> dict:
        """Book an appointment slot via Cal.com"""
        payload = {
            "date": date,
            "time": time,
            "phone_number": phone_number,
            "name": name or phone_number,
            "event_type": "default",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/bookings",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                return resp.json() if resp.status_code == 200 else {"error": resp.text}
            except httpx.ConnectError:
                return {"error": "Calendar service not available"}

    async def get_slots(self, date: str) -> list:
        """Get available slots for a date"""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(f"{self.base_url}/api/slots?date={date}")
                return resp.json().get("slots", []) if resp.status_code == 200 else []
            except httpx.ConnectError:
                return []

    async def cancel_booking(self, booking_id: str) -> dict:
        """Cancel an existing booking"""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.delete(f"{self.base_url}/api/bookings/{booking_id}")
                return resp.json() if resp.status_code == 200 else {"error": resp.text}
            except httpx.ConnectError:
                return {"error": "Calendar service not available"}
</arg_value>
</write_to_file></tool_call>