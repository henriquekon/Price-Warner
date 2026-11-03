"""Per-user alert history and read state for the React alert center."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from data.models import (
    AlertMetadata, Monitoring, NotificationEvent, PriceHistory,
    Product, SessionLocal, Store, User,
)
from engine.auth import current_user

router = APIRouter(prefix="/alerts", tags=["alerts"])


def get_db():
    with SessionLocal() as db:
        yield db


def _owned_events(db: Session, user_id: int):
    return (db.query(NotificationEvent)
            .join(Monitoring, NotificationEvent.monitoring_id == Monitoring.id)
            .filter(Monitoring.user_id == user_id))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("")
def list_alerts(
    status: Literal["all", "sent", "failed", "pending"] = "all",
    period: Literal["7d", "30d", "90d", "all"] = "30d",
    store_id: str = Query("all", max_length=64),
    q: str = Query("", max_length=100),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    base = _owned_events(db, user.id)
    counts = dict(base.with_entities(NotificationEvent.status, func.count(NotificationEvent.id))
                  .group_by(NotificationEvent.status).all())
    total_all = sum(counts.values())
    unread = (base.outerjoin(AlertMetadata, AlertMetadata.event_id == NotificationEvent.id)
              .filter(NotificationEvent.status.in_(("sent", "failed")),
                      AlertMetadata.read_at.is_(None)).count())

    query = (db.query(NotificationEvent, Monitoring, PriceHistory, Product, Store, AlertMetadata)
             .join(Monitoring, Monitoring.id == NotificationEvent.monitoring_id)
             .join(PriceHistory, PriceHistory.id == NotificationEvent.price_history_id)
             .join(Product, Product.id == Monitoring.product_id)
             .outerjoin(Store, Store.id == Product.store_id)
             .outerjoin(AlertMetadata, AlertMetadata.event_id == NotificationEvent.id)
             .filter(Monitoring.user_id == user.id))
    if status != "all":
        query = query.filter(NotificationEvent.status == status)
    if period != "all":
        query = query.filter(NotificationEvent.created_at >= _utc_now() - timedelta(days=int(period[:-1])))
    if store_id != "all":
        query = query.filter(Product.store_id == store_id)
    if q.strip():
        query = query.filter(Product.name.ilike(f"%{q.strip()}%"))
    total = query.count()
    rows = query.order_by(NotificationEvent.created_at.desc(), NotificationEvent.id.desc()).offset(offset).limit(limit).all()
    items = []
    for event, monitoring, history, product, store, meta in rows:
        reference = meta.reference_price if meta is not None else None
        change = None
        if reference is not None and reference > 0 and history.price is not None:
            change = round((history.price - reference) / reference * 100, 2)
        items.append({
            "id": event.id,
            "product_id": product.id,
            "product_name": product.name,
            "product_url": product.url,
            "store_id": product.store_id,
            "store_name": store.name if store else product.store_id,
            "price": history.price,
            "currency": "BRL",
            "reference_price": reference,
            "previous_alert_price": meta.previous_alert_price if meta else None,
            "change_percent": change,
            "reason": meta.reason if meta else None,
            "kind": meta.kind if meta else None,
            "status": event.status,
            "created_at": event.created_at,
            "sent_at": event.sent_at,
            "read": meta.read_at is not None if meta else False,
            "error": event.error if event.status == "failed" else None,
        })
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": {
            "total": total_all, "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0), "pending": counts.get("pending", 0),
            "unread": unread,
        },
    }


@router.patch("/{event_id}/read")
def mark_alert_read(event_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    event = _owned_events(db, user.id).filter(NotificationEvent.id == event_id).first()
    if event is None:
        raise HTTPException(404, "Alert not found")
    meta = db.get(AlertMetadata, event.id)
    if meta is None:
        meta = AlertMetadata(event_id=event.id)
        db.add(meta)
    if meta.read_at is None:
        meta.read_at = _utc_now()
    db.commit()
    return {"id": event.id, "read": True}


@router.post("/read-all")
def mark_all_alerts_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    events = (_owned_events(db, user.id)
              .outerjoin(AlertMetadata, AlertMetadata.event_id == NotificationEvent.id)
              .filter(NotificationEvent.status.in_(("sent", "failed")),
                      AlertMetadata.read_at.is_(None))
              .all())
    now = _utc_now()
    for event in events:
        meta = db.get(AlertMetadata, event.id)
        if meta is None:
            meta = AlertMetadata(event_id=event.id)
            db.add(meta)
        meta.read_at = now
    db.commit()
    return {"marked": len(events)}
