import asyncio
from datetime import datetime, timedelta
from sqlalchemy import func
from data.models import SessionLocal, Product, PriceHistory
from engine.scraper import AddonScraper
from engine.notifier import Notifier

def check_price_alerts(session, product, current_price):
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    # Busca estatísticas do período
    stats = session.query(
        func.avg(PriceHistory.price).label('avg_price'),
        func.min(PriceHistory.price).label('min_recent')
    ).filter(
        PriceHistory.product_id == product.id,
        PriceHistory.fetched_at >= thirty_days_ago,
        PriceHistory.price.is_not(None)
    ).one()

    avg_price = stats.avg_price
    min_recent = stats.min_recent

    # Se não houver histórico (produto novo), não há base para comparação relativa ainda
    if avg_price is None:
        return []

    alerts = []
    threshold = product.target_drop_percentage / 100

    # RULE 1: Significiant Drop from Recent Average
    if current_price <= (avg_price * (1 - threshold)):
        alerts.append(f"Relevant drop from recent average (R$ {avg_price:.2f} → R$ {current_price:.2f})")

    # RULE 2: New 30-Day Low
    if current_price < min_recent:
        alerts.append(f"New 30-day low (Previous: R$ {min_recent:.2f})")

    return alerts

async def price_scheduler():
    notifier = Notifier()
    
    while True:
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            products = db.query(Product).filter(Product.is_active == True).all()

            for product in products:
                next_check = (product.last_checked or datetime.min) + timedelta(minutes=product.interval)

                if now >= next_check:
                    print(f"[*] Verifying: {product.name}...")
                    scraper = AddonScraper(f"addons/{product.store_id}.json")
                    data = scraper.scrape(product.url)
                    
                    if data["ok"]:
                        current_price = data["price"]
                        
                        # At this point, we have the current price and can check for alerts before saving
                        alerts = check_price_alerts(db, product, current_price)
                        
                        # Then, we save the price history regardless of alerts, to maintain a complete record
                        scraper.save_to_db(data)
                        
                        if alerts:
                            reasons = " | ".join(alerts)
                            msg = (f"📉 OPORTUNITY: {product.name}\n"
                                   f"Price: R$ {current_price:.2f}\n"
                                   f"Reason: {reasons}\n"
                                   f"Link: {product.url}")
                            notifier.send(msg)
                        
                        product.last_checked = now
                        db.commit()
                    else:
                        print(f" [!] Fail when scraping {product.name}")
        
        except Exception as e:
            print(f" [CORE ERROR] {e}")
            db.rollback()
        finally:
            db.close()
            
        await asyncio.sleep(60)