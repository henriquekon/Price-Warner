"""Authenticated product history and per-user monitoring settings."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from data.models import Monitoring, PriceHistory, Product, User
from engine.auth import current_user, get_db

router = APIRouter(prefix="/products", tags=["product-details"])


class MonitoringUpdate(BaseModel):
    interval: int = Field(ge=1, le=10080)
    target_drop_percentage: float = Field(gt=0, le=100)
    is_active: bool


def owned_product(db: Session, user: User, product_id: int):
    row = (db.query(Product, Monitoring)
           .join(Monitoring, Monitoring.product_id == Product.id)
           .filter(Product.id == product_id, Monitoring.user_id == user.id).first())
    if row is None:
        raise HTTPException(404, "Monitoring not found")
    return row


@router.get("/{product_id}/details")
def product_details(product_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    product, monitoring = owned_product(db, user, product_id)
    observations = (db.query(PriceHistory)
                    .filter(PriceHistory.product_id == product_id)
                    .order_by(PriceHistory.fetched_at.desc(), PriceHistory.id.desc())
                    .limit(500).all())
    return {
        "id": product.id,
        "name": product.name,
        "url": product.url,
        "store_id": product.store_id,
        "image_url": product.image_url,
        "last_checked": product.last_checked,
        "last_error": product.last_error,
        "interval": monitoring.interval,
        "target_drop_percentage": monitoring.target_drop_percentage,
        "is_active": monitoring.is_active,
        "history": [
            {"id": row.id, "price": row.price, "availability": row.availability,
             "fetched_at": row.fetched_at, "strategy_used": row.strategy_used}
            for row in reversed(observations)
        ],
    }


@router.patch("/{product_id}/monitoring")
def update_monitoring(product_id: int, update: MonitoringUpdate,
                      db: Session = Depends(get_db), user: User = Depends(current_user)):
    _, monitoring = owned_product(db, user, product_id)
    monitoring.interval = update.interval
    monitoring.target_drop_percentage = update.target_drop_percentage
    monitoring.is_active = update.is_active
    db.commit()
    return {"id": product_id, "interval": monitoring.interval,
            "target_drop_percentage": monitoring.target_drop_percentage,
            "is_active": monitoring.is_active}
