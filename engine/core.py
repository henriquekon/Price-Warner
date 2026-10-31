import asyncio
import logging
from datetime import datetime, timedelta


from data.models import PriceHistory, Product, SessionLocal, Monitoring, NotificationSettings, NotificationEvent, User
from engine.config import ADDONS_DIR, SCHEDULER_INTERVAL_SECONDS
from engine.notifier import Notifier
from engine.scraper import AddonScraper
from engine.email_service import send_email
from engine.alert_rules import opportunity_reasons, should_notify

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

            account_alerts = []
            for monitoring in monitorings:
                if product.last_checked is not None and now < product.last_checked + timedelta(minutes=monitoring.interval):
                    continue
                from types import SimpleNamespace
                rule = SimpleNamespace(id=product.id, target_drop_percentage=monitoring.target_drop_percentage)
                reasons = check_price_alerts(db, rule, result["price"])
                if reasons:
                    account_alerts.append((monitoring.id, monitoring.user_id, reasons))
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
                latest = db.query(NotificationEvent).filter(
                    NotificationEvent.monitoring_id == monitoring_id,
                    NotificationEvent.status == "sent",
                ).order_by(NotificationEvent.sent_at.desc()).first()
                last_sent_price = None
                prices_since_last_sent = []
                if latest is not None:
                    previous = db.get(PriceHistory, latest.price_history_id)
                    if previous is not None:
                        last_sent_price = previous.price
                    if latest.sent_at is not None:
                        prices_since_last_sent = [row[0] for row in db.query(PriceHistory.price).filter(
                            PriceHistory.product_id == product.id,
                            PriceHistory.fetched_at > latest.sent_at,
                            PriceHistory.id != history.id,
                            PriceHistory.price.is_not(None),
                        ).all()]
                if not should_notify(result["price"], last_sent_price, prices_since_last_sent):
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
