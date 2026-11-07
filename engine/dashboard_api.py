"""Dashboard data for the React interface."""
from engine.image_cache import image_proxy_url
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from data.models import Monitoring, PriceHistory, Product, User
from engine.auth import current_user, get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(period: Literal["last", "24h", "7d", "30d"] = "7d",
              page: int = Query(1, ge=1, le=100000),
              page_size: int = Query(20, ge=5, le=100),
              q: str = Query("", max_length=120),
              store_id: str = Query("all", max_length=64),
              status: Literal["all", "active", "drops", "errors"] = "all",
              db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = (db.query(Product, Monitoring)
            .join(Monitoring, Monitoring.product_id == Product.id)
            .filter(Monitoring.user_id == user.id)
            .order_by(Product.id.desc()).all())
    product_ids = [product.id for product, _ in rows]
    history = {}
    last_availability = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
    cutoff = now - days[period] if period != "last" else None
    if product_ids:
        records = (db.query(PriceHistory)
                   .filter(PriceHistory.product_id.in_(product_ids))
                   .order_by(PriceHistory.product_id, PriceHistory.fetched_at.desc(), PriceHistory.id.desc())
                   .all())
        for item in records:
            last_availability.setdefault(item.product_id, item.availability or "unknown")
            entries = history.setdefault(item.product_id, [])
            if item.price is not None:
                if period == "last" and len(entries) >= 2:
                    continue
                entries.append(item)
    items = []
    for product, monitoring in rows:
        prices = history.get(product.id, [])
        latest = prices[0] if prices else None
        if period == "last":
            previous = prices[1] if len(prices) > 1 else None
        else:
            in_window = [entry for entry in prices if entry.fetched_at >= cutoff]
            previous = in_window[-1] if len(in_window) > 1 else None
        unavailable = last_availability.get(product.id) == "out_of_stock"
        change = ((latest.price - previous.price) / previous.price * 100
                  if latest and previous and previous.price > 0 and not unavailable else None)
        items.append({
            "id": product.id, "name": product.name, "url": product.url,
            "store_id": product.store_id, "image_url": product.image_url,
            "image_proxy_url": image_proxy_url(product.image_url, product.store_id),
            "is_active": monitoring.is_active, "interval": monitoring.interval,
            "target_drop_percentage": monitoring.target_drop_percentage,
            "last_checked": product.last_checked, "last_error": product.last_error,
            "price": latest.price if latest else None,
            "previous_price": previous.price if previous else None,
            "price_change_percent": round(change, 2) if change is not None else None,
            "availability": last_availability.get(product.id, "unknown"),
            "currency": "BRL",
        })
    matching = [item for item in items if
                (store_id == "all" or item["store_id"] == store_id) and
                (status != "active" or item["is_active"]) and
                (status != "errors" or item["last_error"]) and
                (status != "drops" or (item["price_change_percent"] is not None and item["price_change_percent"] < 0)) and
                (not q.strip() or q.strip().casefold() in f"{item['name']} {item['store_id']}".casefold())]
    start = (page - 1) * page_size
    return {
        "pagination": {"page": page, "page_size": page_size, "total": len(matching),
                       "pages": max(1, (len(matching) + page_size - 1) // page_size)},
        "summary": {
            "total": len(items),
            "active": sum(1 for item in items if item["is_active"]),
            "price_drops": sum(1 for item in items if item["price_change_percent"] is not None and item["price_change_percent"] < 0),
            "errors": sum(1 for item in items if item["last_error"]),
        },
        "period": period,
        "products": matching[start:start + page_size],
    }
