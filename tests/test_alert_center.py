"""Alert history exposes only the signed-in user's events."""
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.models import (
    AlertMetadata, Base, Monitoring, NotificationEvent, PriceHistory, Product, Store, User,
)
from engine.auth import current_user
from engine.alerts_api import get_db as alert_db
from main import app


def test_alert_center_filters_permissions_and_read_state(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'alerts.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    now = datetime.utcnow()
    with sessions.begin() as db:
        db.add_all([User(id=1, email="first@example.test"), User(id=2, email="second@example.test")])
        db.add(Store(id="kabum", name="KaBuM"))
        db.add_all([
            Product(id=1, name="Laptop", url="https://www.kabum.com.br/produto/1", store_id="kabum"),
            Product(id=2, name="Private monitor", url="https://www.kabum.com.br/produto/2", store_id="kabum"),
        ])
        db.flush()
        db.add_all([
            Monitoring(id=10, user_id=1, product_id=1),
            Monitoring(id=20, user_id=2, product_id=2),
        ])
        db.add_all([
            PriceHistory(id=101, product_id=1, price=90, fetched_at=now),
            PriceHistory(id=102, product_id=1, price=80, fetched_at=now),
            PriceHistory(id=103, product_id=1, price=70, fetched_at=now - timedelta(days=60)),
            PriceHistory(id=201, product_id=2, price=55, fetched_at=now),
        ])
        db.flush()
        db.add_all([
            NotificationEvent(id=1, monitoring_id=10, price_history_id=101, status="sent", sent_at=now, created_at=now),
            NotificationEvent(id=2, monitoring_id=10, price_history_id=102, status="failed", error="SMTPConnectError", created_at=now - timedelta(hours=1)),
            NotificationEvent(id=3, monitoring_id=10, price_history_id=103, status="sent", sent_at=now - timedelta(days=60), created_at=now - timedelta(days=60)),
            NotificationEvent(id=4, monitoring_id=20, price_history_id=201, status="sent", sent_at=now, created_at=now),
        ])
        db.flush()
        db.add(AlertMetadata(event_id=1, reference_price=100, previous_alert_price=95,
                             reason="Price dropped from reference", kind="additional_drop"))

    def override_db():
        with sessions() as db:
            yield db

    def override_user():
        with sessions() as db:
            yield db.get(User, 1)

    app.dependency_overrides[alert_db] = override_db
    app.dependency_overrides[current_user] = override_user
    try:
        with TestClient(app) as client:
            response = client.get("/alerts?period=all")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["summary"] == {"total": 3, "sent": 2, "failed": 1, "pending": 0, "unread": 3}
            assert [item["id"] for item in data["items"]] == [1, 2, 3]
            assert data["items"][0]["change_percent"] == -10.0
            assert data["items"][0]["kind"] == "additional_drop"
            assert data["items"][1]["reason"] is None
            assert client.get("/alerts?period=30d").json()["total"] == 2
            assert client.get("/alerts?period=all&status=failed").json()["items"][0]["id"] == 2
            assert client.get("/alerts?period=all&q=unrelated").json()["items"] == []
            assert client.get("/alerts?period=all&store_id=amazon_br").json()["items"] == []
            assert client.get("/alerts?period=all&limit=1&offset=1").json()["items"][0]["id"] == 2
            assert client.patch("/alerts/4/read").status_code == 404
            assert client.patch("/alerts/1/read").status_code == 200
            assert client.patch("/alerts/1/read").status_code == 200
            assert client.get("/alerts").json()["summary"]["unread"] == 2
            assert client.post("/alerts/read-all").json()["marked"] == 2
            assert client.get("/alerts?period=all").json()["summary"]["unread"] == 0
            assert client.post("/alerts/read-all").json()["marked"] == 0
            assert client.get("/alerts?period=all&limit=0").status_code == 422
            assert client.get("/alerts?period=all&limit=101").status_code == 422
        with sessions() as db:
            assert db.get(AlertMetadata, 4) is None
            assert db.get(AlertMetadata, 1).reference_price == 100
            assert db.get(AlertMetadata, 2).read_at is not None
            assert db.get(AlertMetadata, 3).read_at is not None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_alert_center_private_mode_requires_session_and_csrf(tmp_path, monkeypatch):
    from engine import auth, auth_api
    from engine.auth import get_db as auth_db, hash_password

    engine = create_engine(f"sqlite:///{tmp_path / 'private.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        db.add(User(email="owner@example.com", password_hash=hash_password("test-password-12345")))
    monkeypatch.setattr(auth, "AUTH_MODE", "private")
    monkeypatch.setattr(auth_api, "AUTH_MODE", "private")

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[auth_db] = override_db
    app.dependency_overrides[alert_db] = override_db
    try:
        with TestClient(app) as client:
            assert client.get("/alerts").status_code == 401
            login = client.post("/auth/login", json={"email": "owner@example.com", "password": "test-password-12345"})
            assert login.status_code == 200, login.text
            assert client.get("/alerts").status_code == 200
            assert client.post("/alerts/read-all").status_code == 403
            csrf = client.get("/auth/csrf").json()["csrf_token"]
            assert client.post("/alerts/read-all", headers={"X-CSRF-Token": csrf}).status_code == 200
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
