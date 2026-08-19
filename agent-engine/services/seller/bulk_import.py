import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db import SellerProduct, SellerListing, SellerOrder


async def import_products_csv(df: pd.DataFrame, session: AsyncSession, client_id: int = 1) -> Dict:
    created = 0
    errors = []
    for _, row in df.iterrows():
        try:
            sku = str(row.get("sku", "")).strip()
            name = str(row.get("name", "")).strip()
            if not sku or not name:
                errors.append(f"SKU and name required: {row.to_dict()}")
                continue

            result = await session.execute(select(SellerProduct).where(SellerProduct.sku == sku))
            existing = result.scalar_one_or_none()
            if existing:
                existing.name = name
                existing.category = str(row.get("category", "")).strip() or None
                existing.cogs = float(row.get("cogs", 0) or 0)
                existing.updated_at = datetime.now(timezone.utc)
            else:
                product = SellerProduct(
                    client_id=client_id,
                    sku=sku,
                    name=name,
                    category=str(row.get("category", "")).strip() or None,
                    cogs=float(row.get("cogs", 0) or 0),
                )
                session.add(product)
            created += 1
        except Exception as e:
            errors.append(str(e))
    await session.commit()
    return {"status": "ok", "created": created, "errors": errors[:10]}


async def import_listings_csv(df: pd.DataFrame, session: AsyncSession, client_id: int = 1) -> Dict:
    created = 0
    errors = []
    for _, row in df.iterrows():
        try:
            sku = str(row.get("sku", "")).strip()
            platform = str(row.get("platform", "")).strip().lower()
            if platform not in ("amazon", "flipkart"):
                errors.append(f"Invalid platform for SKU {sku}: {platform}")
                continue

            result = await session.execute(select(SellerProduct).where(SellerProduct.sku == sku))
            product = result.scalar_one_or_none()
            if not product:
                errors.append(f"Product not found for SKU: {sku}")
                continue

            listing = SellerListing(
                client_id=client_id,
                product_id=product.id,
                platform=platform,
                listing_id=str(row.get("listing_id", "")).strip(),
                title=str(row.get("title", "")).strip(),
                bullets=str(row.get("bullets", "")).strip() or None,
                description=str(row.get("description", "")).strip() or None,
                backend_keywords=str(row.get("backend_keywords", "")).strip() or None,
                price=float(row.get("price", 0) or 0),
                stock=int(row.get("stock", 0) or 0),
            )
            session.add(listing)
            created += 1
        except Exception as e:
            errors.append(str(e))
    await session.commit()
    return {"status": "ok", "created": created, "errors": errors[:10]}


async def import_orders_csv(df: pd.DataFrame, session: AsyncSession, client_id: int = 1) -> Dict:
    created = 0
    errors = []
    for _, row in df.iterrows():
        try:
            sku = str(row.get("sku", "")).strip()
            platform = str(row.get("platform", "")).strip().lower()
            if platform not in ("amazon", "flipkart"):
                errors.append(f"Invalid platform for order {row.get('order_id', '')}: {platform}")
                continue

            result = await session.execute(select(SellerProduct).where(SellerProduct.sku == sku))
            product = result.scalar_one_or_none()
            product_id = product.id if product else None

            order = SellerOrder(
                client_id=client_id,
                product_id=product_id,
                platform=platform,
                order_id=str(row.get("order_id", "")).strip(),
                customer_name=str(row.get("customer_name", "")).strip() or None,
                customer_phone=str(row.get("customer_phone", "")).strip() or None,
                quantity=int(row.get("quantity", 1) or 1),
                unit_price=float(row.get("unit_price", 0) or 0),
                tax=float(row.get("tax", 0) or 0),
                shipping=float(row.get("shipping", 0) or 0),
                total=float(row.get("total", 0) or 0),
                status=str(row.get("status", "pending")).strip(),
                payment_status=str(row.get("payment_status", "pending")).strip(),
                fulfillment_status=str(row.get("fulfillment_status", "unfulfilled")).strip(),
                shipping_address=str(row.get("shipping_address", "")).strip() or None,
                tracking_id=str(row.get("tracking_id", "")).strip() or None,
                notes=str(row.get("notes", "")).strip() or None,
            )
            session.add(order)
            created += 1
        except Exception as e:
            errors.append(str(e))
    await session.commit()
    return {"status": "ok", "created": created, "errors": errors[:10]}
