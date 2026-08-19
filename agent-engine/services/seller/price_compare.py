from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from db import SellerProduct, SellerListing, PriceHistory, PriceAlert


async def compare_product_price(product_id: int, session: AsyncSession, client_id: int = 1) -> Dict:
    result = await session.execute(select(SellerProduct).where(SellerProduct.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise ValueError("Product not found")

    result = await session.execute(
        select(SellerListing).where(SellerListing.product_id == product_id).where(SellerListing.is_active == True)
    )
    listings = result.scalars().all()

    comparison = {
        "product_id": product_id,
        "sku": product.sku,
        "platform": "multiple",
        "my_price": 0.0,
        "competitor_prices": [],
        "best_price": 0.0,
        "price_delta": 0.0,
        "alert_triggered": False,
    }

    my_prices = [l.price for l in listings if l.platform in ("amazon", "flipkart")]
    if my_prices:
        comparison["my_price"] = min(my_prices)

    for listing in listings:
        if listing.platform in ("amazon", "flipkart"):
            comparison["competitor_prices"].append({
                "platform": listing.platform,
                "listing_id": listing.listing_id,
                "price": listing.price,
                "stock": listing.stock,
            })

    if comparison["competitor_prices"]:
        prices = [c["price"] for c in comparison["competitor_prices"]]
        comparison["best_price"] = min(prices)
        comparison["price_delta"] = round(comparison["my_price"] - comparison["best_price"], 2) if comparison["my_price"] else 0.0

        if comparison["price_delta"] > 0:
            alert = PriceAlert(
                client_id=client_id,
                product_id=product_id,
                platform="multiple",
                alert_type="undercut",
                message=f"Competitor undercuts by ₹{comparison['price_delta']}",
                my_price=comparison["my_price"],
                competitor_price=comparison["best_price"],
            )
            session.add(alert)
            comparison["alert_triggered"] = True

    return comparison


async def record_price_history(product_id: int, platform: str, my_price: float, competitor_price: float, competitor_name: str = None, session: AsyncSession = None, client_id: int = 1):
    if session is None:
        from db import async_session
        async with async_session() as s:
            await _save_price_history(s, product_id, platform, my_price, competitor_price, competitor_name, client_id)
    else:
        await _save_price_history(session, product_id, platform, my_price, competitor_price, competitor_name, client_id)


async def _save_price_history(session: AsyncSession, product_id: int, platform: str, my_price: float, competitor_price: float, competitor_name: str = None, client_id: int = 1):
    history = PriceHistory(
        client_id=client_id,
        product_id=product_id,
        platform=platform,
        my_price=my_price,
        competitor_price=competitor_price,
        competitor_name=competitor_name,
        price_delta=round(my_price - competitor_price, 2),
    )
    session.add(history)


async def get_price_trends(product_id: int, days: int = 30, session: AsyncSession = None, client_id: int = 1) -> List[Dict]:
    if session is None:
        from db import async_session
        async with async_session() as s:
            return await _fetch_trends(s, product_id, days, client_id)
    else:
        return await _fetch_trends(session, product_id, days, client_id)


async def _fetch_trends(session: AsyncSession, product_id: int, days: int, client_id: int = 1) -> List[Dict]:
    since = datetime.now() - timedelta(days=days)
    result = await session.execute(
        select(PriceHistory)
        .where(PriceHistory.product_id == product_id)
        .where(PriceHistory.client_id == client_id)
        .where(PriceHistory.recorded_at >= since)
        .order_by(PriceHistory.recorded_at.asc())
    )
    history = result.scalars().all()
    return [
        {
            "date": h.recorded_at.isoformat(),
            "my_price": h.my_price,
            "competitor_price": h.competitor_price,
            "delta": h.price_delta,
        }
        for h in history
    ]
