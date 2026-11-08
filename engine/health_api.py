"""Authenticated worker heartbeat and per-account monitoring diagnostics."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from data.models import Monitoring, NotificationEvent, Product, User, WorkerState
from engine.auth import current_user, get_db
from engine.config import SCHEDULER_INTERVAL_SECONDS

router = APIRouter(prefix="/system", tags=["system"])


def worker_health(db: Session, now: datetime, include_counts: bool = False) -> dict:
    state = db.get(WorkerState, 1)
    if state is None or state.last_started_at is None:
        return {"status": "not_started", "last_started_at": None,
                "last_finished_at": None, "last_success_at": None, "last_cycle": None}
    stale_after = max(300, SCHEDULER_INTERVAL_SECONDS * 3)
    latest_activity = state.last_progress_at or state.last_started_at
    if now - latest_activity > timedelta(seconds=stale_after):
        status = "stale"
    elif state.state == "error":
        status = "error"
    elif state.state == "running":
        status = "running"
    elif state.last_failed:
        status = "degraded"
    else:
        status = "healthy"
    return {
        "status": status,
        "last_started_at": state.last_started_at,
        "last_finished_at": state.last_finished_at,
        "last_success_at": state.last_success_at,
        "last_cycle": ({
            "due": state.last_due, "checked": state.last_checked,
            "failed": state.last_failed, "out_of_stock": state.last_out_of_stock,
        } if include_counts else None),
    }


@router.get("/health")
def system_health(db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.utcnow()
    rows = (db.query(Product, Monitoring)
            .join(Monitoring, Monitoring.product_id == Product.id)
            .filter(Monitoring.user_id == user.id)
            .all())
    by_store: dict[str, dict] = {}
    errors = []
    pending = overdue = active = 0
    for product, monitoring in rows:
        if not monitoring.is_active:
            continue
        active += 1
        store = by_store.setdefault(product.store_id, {
            "store_id": product.store_id, "monitored": 0,
            "errors": 0, "pending": 0, "overdue": 0,
        })
        store["monitored"] += 1
        if product.last_checked is None:
            pending += 1
            store["pending"] += 1
        elif now - product.last_checked > timedelta(minutes=max(5, monitoring.interval * 2)):
            overdue += 1
            store["overdue"] += 1
        if product.last_error:
            store["errors"] += 1
            errors.append({
                "product_id": product.id,
                "product_name": product.name,
                "store_id": product.store_id,
                "error": product.last_error,
                "last_checked": product.last_checked,
            })
    errors.sort(key=lambda item: item["last_checked"] or datetime.min, reverse=True)
    failed_emails = (db.query(NotificationEvent.id)
                     .join(Monitoring, Monitoring.id == NotificationEvent.monitoring_id)
                     .filter(Monitoring.user_id == user.id,
                             NotificationEvent.status == "failed",
                             NotificationEvent.created_at >= now - timedelta(days=7))
                     .count())
    return {
        "worker": worker_health(db, now, include_counts=user.is_admin),
        "summary": {"monitored": active, "errors": len(errors),
                    "pending": pending, "overdue": overdue,
                    "failed_emails_7d": failed_emails},
        "stores": sorted(by_store.values(), key=lambda item: item["store_id"]),
        "recent_errors": errors[:10],
    }
