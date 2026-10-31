import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from data.models import PriceHistory, Product, SessionLocal
from engine.config import ADDONS_DIR, SCHEDULER_INTERVAL_SECONDS
from engine.notifier import Notifier
from engine.scraper import AddonScraper

logger = logging.getLogger(__name__)


def check_price_alerts(session, product, current_price):
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    stats = session.query(
        func.avg(PriceHistory.price).label("avg_price"),
        func.min(PriceHistory.price).label("min_recent"),
    ).filter(
        PriceHistory.product_id == product.id,
        PriceHistory.fetched_at >= thirty_days_ago,
        PriceHistory.price.is_not(None),
    ).one()

    if stats.avg_price is None:
        return []

    alerts = []
    threshold = product.target_drop_percentage / 100
    if current_price <= stats.avg_price * (1 - threshold):
        alerts.append(
            f"Relevant drop from recent average (R$ {stats.avg_price:.2f} -> R$ {current_price:.2f})"
        )
    if current_price < stats.min_recent:
        alerts.append(f"New 30-day low (Previous: R$ {stats.min_recent:.2f})")
    return alerts


def check_product(product_id: int, notifier: Notifier):
    with SessionLocal() as db:
        product = db.get(Product, product_id)
        if product is None or not product.is_active:
            return

        now = datetime.utcnow()
        if product.last_checked is not None and now < product.last_checked + timedelta(minutes=product.interval):
            return

        logger.info("Checking product %s", product.name)
        try:
            addon_path = ADDONS_DIR / f"{product.store_id}.json"
            with AddonScraper(addon_path) as scraper:
                result = scraper.scrape(product.url)

            if not result["ok"]:
                raise ValueError("No valid price extracted")

            alerts = check_price_alerts(db, product, result["price"])
            db.add(PriceHistory(
                product_id=product.id,
                price=result["price"],
                availability=result.get("availability") or "unknown",
                strategy_used=result.get("strategies_used", {}).get("price"),
            ))
            product.last_checked = now
            product.last_error = None
            db.commit()

            if alerts:
                notifier.send(
                    f"OPPORTUNITY: {product.name}\n"
                    f"Price: R$ {result['price']:.2f}\n"
                    f"Reason: {' | '.join(alerts)}\nLink: {product.url}"
                )
        except Exception as exc:
            db.rollback()
            product.last_error = str(exc)[:500]
            product.last_checked = now
            db.commit()
            logger.exception("Failed checking product %s", product_id)


def run_due_checks(notifier: Notifier):
    now = datetime.utcnow()
    with SessionLocal() as db:
        due_ids = [product.id for product in db.query(Product).filter(Product.is_active.is_(True)).all()
                   if product.last_checked is None or now >= product.last_checked + timedelta(minutes=product.interval)]
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
