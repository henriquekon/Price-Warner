import asyncio
import logging
import time
import httpx
from datetime import datetime, timedelta


from data.models import PriceHistory, Product, SessionLocal, Monitoring, NotificationSettings, NotificationEvent, User, WorkerState
from engine.config import ADDONS_DIR, SCHEDULER_INTERVAL_SECONDS
from engine.notifier import Notifier
from engine.scraper import AddonScraper
from engine.addons.registry import load_addon
from engine.media import validate_product_image_url
from engine.email_service import send_email
from engine.alert_rules import ADDITIONAL_DROP_PERCENT, cooldown_allows_alert, opportunity_reasons
from engine.cycle_rules import evaluate_cycle, mark_delivered
from engine.cycle_state import read_snapshot, write_snapshot
from data.models import PriceCycleState, AlertMetadata

logger = logging.getLogger(__name__)


def check_price_alerts(session, product, current_price):
    """Evaluate changes against a robust 30-day reference before saving the new price."""
    cutoff = datetime.utcnow() - timedelta(days=30)
    prices = [row[0] for row in session.query(PriceHistory.price).filter(
        PriceHistory.product_id == product.id,
        PriceHistory.fetched_at >= cutoff,
        PriceHistory.price.is_not(None),
    ).all()]
    return opportunity_reasons(prices, current_price, product.target_drop_percentage)


def check_product(product_id: int, notifier: Notifier):
    started = time.monotonic()
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        if product is None or not product.is_active:
            return "skipped"
        monitorings = db.query(Monitoring).filter(Monitoring.product_id == product_id, Monitoring.is_active.is_(True)).all()
        if not monitorings:
            return "skipped"

        now = datetime.utcnow()
        interval = min(m.interval for m in monitorings)
        if product.last_checked is not None and now < product.last_checked + timedelta(minutes=interval):
            return "skipped"

        logger.info("price_check_start product_id=%s store=%s", product.id, product.store_id)
        result = {}
        try:
            addon_path = ADDONS_DIR / f"{product.store_id}.json"
            with AddonScraper(addon_path) as scraper:
                result = scraper.scrape(product.url)

            if not result.get("ok"):
                code = result.get("status") or "price_unavailable"
                reason = result.get("reason") or "Reliable price not extracted"
                raise ValueError(f"{code}: {reason}")
            if result.get("availability") != "out_of_stock" and result.get("price") is None:
                raise ValueError("price_unavailable: missing price for available product")

            cutoff = now - timedelta(days=30)
            prior_prices = [row[0] for row in db.query(PriceHistory.price).filter(
                PriceHistory.product_id == product.id,
                PriceHistory.fetched_at >= cutoff,
                PriceHistory.price.is_not(None),
                PriceHistory.availability != "out_of_stock",
            ).all()]
            account_alerts = []
            for monitoring in monitorings:
                state = db.get(PriceCycleState, monitoring.id)
                if state is None:
                    state = PriceCycleState(monitoring_id=monitoring.id)
                    db.add(state)
                    db.flush()
                    previous_delivery = db.query(NotificationEvent).filter(
                        NotificationEvent.monitoring_id == monitoring.id,
                        NotificationEvent.status == "sent",
                    ).order_by(NotificationEvent.sent_at.desc()).first()
                    if previous_delivery is not None:
                        prior_alert = db.get(PriceHistory, previous_delivery.price_history_id)
                        if prior_alert is not None:
                            state.last_alert_price = prior_alert.price
                            state.last_alert_at = previous_delivery.sent_at
                if product.last_checked is not None and now < product.last_checked + timedelta(minutes=monitoring.interval):
                    continue
                if result.get("availability") == "out_of_stock":
                    continue
                decision = evaluate_cycle(read_snapshot(state), prior_prices, result["price"],
                                          monitoring.target_drop_percentage, now)
                write_snapshot(state, decision.snapshot)
                if decision.should_send:
                    kind = "first_drop" if state.last_alert_price is None else (
                        "additional_drop" if result["price"] <= state.last_alert_price * (1 - ADDITIONAL_DROP_PERCENT / 100)
                        else "recovery"
                    )
                    account_alerts.append((
                        monitoring.id, monitoring.user_id, decision.reasons,
                        decision.reference, state.last_alert_price, state.last_alert_at, kind,
                    ))
            history = PriceHistory(
                product_id=product.id,
                price=result["price"],
                availability=result.get("availability") or "unknown",
                strategy_used=result.get("strategies_used", {}).get("price"),
            )
            db.add(history)
            db.flush()
            image_url = validate_product_image_url(result.get("image_url"), load_addon(addon_path))
            if image_url:
                product.image_url = image_url
            product.last_checked = now
            product.last_error = None
            db.commit()

            for monitoring_id, user_id, reasons, reference, previous_price, previous_at, kind in account_alerts:
                message = (f"OPPORTUNITY for account {user_id}: {product.name}\n"
                           f"Price: R$ {result['price']:.2f}\n"
                           f"Reason: {' | '.join(reasons)}\nLink: {product.url}")
                settings = db.get(NotificationSettings, user_id)
                if not settings or not settings.enabled:
                    continue
                if not cooldown_allows_alert(kind, previous_at, now, settings.cooldown_hours):
                    continue
                state = db.get(PriceCycleState, monitoring_id)
                if state is None:
                    continue
                event = NotificationEvent(monitoring_id=monitoring_id,
                                          price_history_id=history.id, status='pending')
                db.add(event)
                db.flush()
                db.add(AlertMetadata(
                    event_id=event.id, reference_price=reference,
                    previous_alert_price=previous_price,
                    reason=" | ".join(reasons)[:500], kind=kind,
                ))
                db.commit()
                try:
                    send_email(settings, settings.recipient_email,
                               f"Price-Warner: price opportunity for {product.name}", message)
                except Exception as exc:
                    event.status = 'failed'
                    event.error = type(exc).__name__[:300]
                    logger.exception('Email delivery failed for monitoring %s', monitoring_id)
                else:
                    event.status = 'sent'
                    event.sent_at = datetime.utcnow()
                    write_snapshot(state, mark_delivered(read_snapshot(state), result["price"], event.sent_at))
                db.commit()
                if event.status == "sent":
                    try:
                        notifier.send(message)
                    except OSError:
                        logger.exception("Notification log write failed for monitoring %s", monitoring_id)
            outcome = "out_of_stock" if result.get("availability") == "out_of_stock" else "ok"
            logger.info(
                "price_check_result product_id=%s store=%s status=%s source=%s duration_ms=%d",
                product_id, product.store_id, outcome,
                result.get("strategies_used", {}).get("price") or "none",
                round((time.monotonic() - started) * 1000),
            )
            return outcome
        except Exception as exc:
            db.rollback()
            product.last_error = str(exc)[:500]
            if result.get("image_url"):
                try:
                    image_url = validate_product_image_url(result["image_url"], load_addon(addon_path))
                    if image_url:
                        product.image_url = image_url
                except Exception:
                    logger.debug("Image validation was unavailable for failed product %s", product_id)
            product.last_checked = now
            db.commit()
            if result.get("status"):
                failure_code = result["status"]
            elif isinstance(exc, httpx.TimeoutException):
                failure_code = "timeout"
            elif isinstance(exc, httpx.HTTPStatusError):
                failure_code = f"http_{exc.response.status_code}"
            elif isinstance(exc, httpx.RequestError):
                failure_code = "network_error"
            else:
                failure_code = "unexpected_error"
            duration = round((time.monotonic() - started) * 1000)
            if isinstance(exc, ValueError) and result.get("status"):
                logger.warning(
                    "price_check_result product_id=%s store=%s status=%s duration_ms=%d",
                    product_id, product.store_id, failure_code, duration,
                )
            else:
                logger.exception(
                    "price_check_result product_id=%s store=%s status=%s duration_ms=%d",
                    product_id, product.store_id, failure_code, duration,
                )
            return "failed"


def _update_worker_state(**fields):
    with SessionLocal() as db:
        state = db.get(WorkerState, 1)
        if state is None:
            state = WorkerState(id=1)
            db.add(state)
        for name, value in fields.items():
            setattr(state, name, value)
        db.commit()


def run_due_checks(notifier: Notifier):
    started = datetime.utcnow()
    _update_worker_state(state="running", last_started_at=started,
                         last_progress_at=started, last_error=None)
    try:
        with SessionLocal() as db:
            monitorings = db.query(Monitoring).filter(Monitoring.is_active.is_(True)).all()
            intervals = {}
            for monitoring in monitorings:
                intervals[monitoring.product_id] = min(
                    monitoring.interval,
                    intervals.get(monitoring.product_id, monitoring.interval),
                )
            products = (db.query(Product)
                        .filter(Product.is_active.is_(True), Product.id.in_(intervals))
                        .all()) if intervals else []
            due_ids = [product.id for product in products
                       if product.last_checked is None
                       or started >= product.last_checked + timedelta(minutes=intervals[product.id])]
        counts = {"ok": 0, "out_of_stock": 0, "failed": 0, "skipped": 0}
        for product_id in due_ids:
            try:
                outcome = check_product(product_id, notifier)
            except Exception:
                logger.exception("price_check_uncaught product_id=%s", product_id)
                outcome = "failed"
            counts[outcome if outcome in counts else "failed"] += 1
            _update_worker_state(last_progress_at=datetime.utcnow())
        completed_at = datetime.utcnow()
        completed = {
            "state": "idle", "last_finished_at": completed_at,
            "last_progress_at": completed_at, "last_due": len(due_ids),
            "last_checked": counts["ok"] + counts["out_of_stock"],
            "last_failed": counts["failed"],
            "last_out_of_stock": counts["out_of_stock"], "last_error": None,
        }
        if not counts["failed"]:
            completed["last_success_at"] = completed_at
        _update_worker_state(**completed)
        logger.info(
            "worker_cycle due=%d checked=%d failed=%d out_of_stock=%d",
            len(due_ids), counts["ok"] + counts["out_of_stock"],
            counts["failed"], counts["out_of_stock"],
        )
        return counts
    except Exception as exc:
        _update_worker_state(
            state="error", last_finished_at=datetime.utcnow(),
            last_error=f"{type(exc).__name__}: scheduler cycle failed",
        )
        raise


async def price_scheduler():
    notifier = Notifier()
    while True:
        try:
            await asyncio.to_thread(run_due_checks, notifier)
        except Exception:
            logger.exception("Price scheduler cycle failed")
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
