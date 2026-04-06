import time
from datetime import datetime, timedelta
from engine.scraper import AddonScraper
from data.models import SessionLocal, Product, init_db

DEFAULT_INTERVAL = 5

def run_scheduler():
    session = SessionLocal()
    products = session.query(Product).filter(Product.is_active == True).all()
    
    now = datetime.utcnow()

    for product in products:
        interval = product.custom_interval if product.custom_interval else DEFAULT_INTERVAL
        
        should_run = False
        if product.last_checked is None:
            should_run = True
        else:
            proxima_checa = product.last_checked + timedelta(minutes=interval)
            if now >= proxima_checa:
                should_run = True

        if should_run:
            print(f"[*] Checando {product.name} ({product.store_id})...")
            addon_path = f"addons/{product.store_id}.json"
            scraper = AddonScraper(addon_path)
            
            data = scraper.scrape(product.url)
            if data["ok"]:
                scraper.save_to_db(data)
                product.last_checked = now
                session.commit()
            
    session.close()

if __name__ == "__main__":
    init_db()
    print("--- Price-Warner Scheduler Iniciado ---")
    while True:
        run_scheduler()
        time.sleep(60)