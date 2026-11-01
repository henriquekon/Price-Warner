"""Period-based dashboard price changes and tenant isolation."""
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from data.models import Base, Monitoring, PriceHistory, Product, Store, User
from engine.auth import current_user
from engine.dashboard_api import get_db
from main import app


def test_comparison_periods_and_no_history():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_factory() as db:
        db.add_all([User(id=1, email="first@example.test"), User(id=2, email="second@example.test"), Store(id="kabum", name="KaBuM!")])
        db.flush()
        for ident in (1, 2):
            db.add(Product(id=ident, name=f"Product {ident}", url=f"https://www.kabum.com.br/produto/{ident}", store_id="kabum"))
        db.flush()
        db.add_all([Monitoring(user_id=1, product_id=1), Monitoring(user_id=2, product_id=2)])
        db.add_all([
            PriceHistory(product_id=1, price=200, fetched_at=now-timedelta(days=12)),
            PriceHistory(product_id=1, price=160, fetched_at=now-timedelta(days=5)),
            PriceHistory(product_id=1, price=120, fetched_at=now-timedelta(hours=3)),
            PriceHistory(product_id=1, price=100, fetched_at=now-timedelta(minutes=10)),
            PriceHistory(product_id=2, price=999, fetched_at=now-timedelta(minutes=5)),
        ])
        db.commit()

    def override_db():
        with session_factory() as db:
            yield db

    def override_user():
        with session_factory() as db:
            yield db.get(User, 1)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = override_user
    try:
        with TestClient(app) as client:
            expected = {"last": -16.67, "24h": -16.67, "7d": -37.5, "30d": -50.0}
            for period, percent in expected.items():
                response = client.get(f"/dashboard?period={period}")
                assert response.status_code == 200
                body = response.json()
                assert body["period"] == period
                assert body["summary"]["total"] == 1
                assert body["products"][0]["price_change_percent"] == percent
                assert body["products"][0]["price"] == 100
            assert client.get("/dashboard").json()["period"] == "7d"
            assert client.get("/dashboard?period=invalid").status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
