import asyncio
import logging
from datetime import datetime, timedelta


from data.models import PriceHistory, Product, SessionLocal, Monitoring, NotificationSettings, NotificationEvent, User
from engine.config import ADDONS_DIR, SCHEDULER_INTERVAL_SECONDS
from engine.notifier import Notifier
from engine.scraper import AddonScraper
from engine.email_service import send_email
from engine.alert_rules import opportunity_reasons
from engine.cycle_rules import evaluate_cycle, mark_delivered
from engine.cycle_state import read_snapshot, write_snapshot
from data.models import PriceCycleState

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
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        if product is None or not product.is_active:
            return
        monitorings = db.query(Monitoring).filter(Monitoring.product_id == product_id, Monitoring.is_active.is_(True)).all()
        if not monitorings:
            return

        now = datetime.utcnow()
        interval = min(m.interval for m in monitorings)
        if product.last_checked is not None and now < product.last_checked + timedelta(minutes=interval):
            return

        logger.info("Checking product %s", product.name)
        try:
            addon_path = ADDONS_DIR / f"{product.store_id}.json"
            with AddonScraper(addon_path) as scraper:
                result = scraper.scrape(product.url)

            if not result["ok"]:
                raise ValueError("No valid price extracted")

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
                    account_alerts.append((monitoring.id, monitoring.user_id, decision.reasons))
            history = PriceHistory(
                product_id=product.id,
                price=result["price"],
                availability=result.get("availability") or "unknown",
                strategy_used=result.get("strategies_used", {}).get("price"),
            )
            db.add(history)
            db.flush()
            product.last_checked = now
            product.last_error = None
            db.commit()

            for monitoring_id, user_id, reasons in account_alerts:
                message = (f"OPPORTUNITY for account {user_id}: {product.name}\n"
                           f"Price: R$ {result['price']:.2f}\n"
                           f"Reason: {' | '.join(reasons)}\nLink: {product.url}")
                settings = db.get(NotificationSettings, user_id)
                if not settings or not settings.enabled:
                    continue
                state = db.get(PriceCycleState, monitoring_id)
                if state is None:
                    continue
                event = NotificationEvent(monitoring_id=monitoring_id,
                                          price_history_id=history.id, status='pending')
                db.add(event)
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
        except Exception as exc:
            db.rollback()
            product.last_error = str(exc)[:500]
            product.last_checked = now
            db.commit()
            logger.exception("Failed checking product %s", product_id)


def run_due_checks(notifier: Notifier):
    now = datetime.utcnow()
    with SessionLocal() as db:
        monitorings = db.query(Monitoring).filter(Monitoring.is_active.is_(True)).all()
        intervals = {}
        for monitoring in monitorings:
            intervals[monitoring.product_id] = min(monitoring.interval, intervals.get(monitoring.product_id, monitoring.interval))
        products = db.query(Product).filter(Product.is_active.is_(True), Product.id.in_(intervals)).all() if intervals else []
        due_ids = [product.id for product in products
                   if product.last_checked is None or now >= product.last_checked + timedelta(minutes=intervals[product.id])]
    for product_id in due_ids:
        check_product(product_id, notifier)


async def price_scheduler():
    notifier = Notifier()
    while True:
        try:
            await asyncio.to_thread(run_due_checks, notifier)
        except Exception:
            logger.exception("Price scheduler cycle failed")
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
