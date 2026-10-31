from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from data.models import Base, PriceHistory, Product, Store
from engine.core import check_price_alerts


def test_alerts_ignore_first_price():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Store(id="test", name="Test"))
        db.flush()
        product = Product(name="Monitor", url="https://example.com/monitor", store_id="test", interval=30)
        db.add(product)
        db.flush()
        assert check_price_alerts(db, product, 900) == []
        for _ in range(3):
            db.add(PriceHistory(product_id=product.id, price=1200, fetched_at=datetime.utcnow() - timedelta(days=1)))
        db.flush()
        alerts = check_price_alerts(db, product, 900)
        assert len(alerts) >= 1
    engine.dispose()
