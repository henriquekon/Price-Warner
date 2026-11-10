"""Database migration, restore and authentication hardening regression tests."""

import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from data.models import Base, Monitoring, Product, Store, User
from deploy.scripts.restore_sqlite import restore
from engine import auth_api
from engine.migrations import REVISIONS, applied_revisions, upgrade
from main import app


def make_engine(folder: Path):
    return create_engine(f"sqlite:///{folder / 'database.db'}", connect_args={"check_same_thread": False})


def test_upgrade_idempotent_and_does_not_claim_other_users_products(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "private")
    database = make_engine(tmp_path)
    Base.metadata.create_all(database)
    with Session(database) as db:
        db.add(Store(id="amazon_br", name="Amazon Brasil"))
        db.add_all([User(id=1, email="other@example.org"), User(id=2, email="local@price-warner.invalid")])
        db.flush()
        db.add(Product(id=1, name="Book", url="https://www.amazon.com.br/dp/123", store_id="amazon_br"))
        db.flush()
        db.add(Monitoring(user_id=1, product_id=1))
        db.commit()
    upgrade(database)
    upgrade(database)
    with Session(database) as db:
        monitorings = db.scalars(select(Monitoring)).all()
        assert len(monitorings) == 1
        assert monitorings[0].user_id == 1
    assert applied_revisions(database) == list(REVISIONS)
    assert "ix_monitorings_user_active" in {index["name"] for index in inspect(database).get_indexes("monitorings")}
    database.dispose()


def test_legacy_upgrade_imports_only_once_and_adds_missing_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    database = make_engine(tmp_path)
    with database.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE stores (id VARCHAR(50) PRIMARY KEY, name VARCHAR(100), is_active BOOLEAN)")
        connection.exec_driver_sql(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR(255), url VARCHAR(1024), "
            "store_id VARCHAR(50), is_active BOOLEAN, interval INTEGER, last_checked DATETIME, "
            "target_drop_percentage FLOAT)"
        )
        connection.exec_driver_sql("INSERT INTO stores (id, name, is_active) VALUES ('kabum', 'KaBuM', 1)")
        connection.exec_driver_sql(
            "INSERT INTO products (id, name, url, store_id, is_active, interval, target_drop_percentage) "
            "VALUES (3, 'GPU', 'https://www.kabum.com.br/produto/3', 'kabum', 1, 60, 15)"
        )
    upgrade(database)
    upgrade(database)
    with Session(database) as db:
        local = db.scalar(select(User).where(User.email == "local@price-warner.invalid"))
        monitoring = db.scalar(select(Monitoring))
        assert local is not None
        assert monitoring is not None
        assert monitoring.user_id == local.id
        assert monitoring.product_id == 3
        assert monitoring.interval == 60
        assert db.scalar(select(Product).where(Product.id == 3)).image_url is None
        assert len(db.scalars(select(Monitoring)).all()) == 1
    assert applied_revisions(database) == list(REVISIONS)
    database.dispose()


def test_restore_recovers_rows_and_keeps_pre_restore_database(tmp_path):
    database = tmp_path / "database.db"
    backup = tmp_path / "old.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE items (value TEXT)")
        db.execute("INSERT INTO items VALUES ('new')")
        db.commit()
    with sqlite3.connect(database) as db, sqlite3.connect(backup) as copy:
        db.execute("UPDATE items SET value='old'")
        db.commit()
        db.backup(copy)
        db.execute("UPDATE items SET value='new'")
        db.commit()
    previous = restore(backup, database, tmp_path / "backups", confirmed=True)
    assert previous is not None and previous.exists()
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT value FROM items").fetchone() == ("old",)
    with sqlite3.connect(previous) as db:
        assert db.execute("SELECT value FROM items").fetchone() == ("new",)
    assert database.stat().st_mode & 0o077 == 0


def test_restore_rejects_corrupt_backup_or_missing_confirmation(tmp_path):
    database = tmp_path / "database.db"
    backup = tmp_path / "corrupt.sqlite3"
    database.write_bytes(b"existing database")
    backup.write_bytes(b"not a sqlite database")
    with pytest.raises(ValueError, match="confirm"):
        restore(backup, database, tmp_path / "backups")
    with pytest.raises(sqlite3.DatabaseError):
        restore(backup, database, tmp_path / "backups", confirmed=True)
    assert database.read_bytes() == b"existing database"


def test_restore_rejects_wal_sidecars(tmp_path):
    database = tmp_path / "database.db"
    backup = tmp_path / "copy.sqlite3"
    database.write_bytes(b"untouched")
    backup.write_bytes(b"data")
    (tmp_path / "database.db-wal").write_bytes(b"WAL")
    with pytest.raises(RuntimeError, match="sidecar"):
        restore(backup, database, tmp_path / "backups", confirmed=True)
    assert database.read_bytes() == b"untouched"


def test_login_failure_limiter_uses_window_and_clears_after_success(monkeypatch):
    fake_time = [100.0]
    monkeypatch.setattr(auth_api.time, "monotonic", lambda: fake_time[0])
    auth_api._login_failures.clear()
    key = ("192.0.2.1", "user@example.com")
    for _ in range(auth_api.LOGIN_FAILURE_LIMIT):
        auth_api._check_login_limit(key)
        auth_api._record_login_result(key, False)
    with pytest.raises(HTTPException) as blocked:
        auth_api._check_login_limit(key)
    assert blocked.value.status_code == 429
    fake_time[0] += auth_api.LOGIN_WINDOW_SECONDS + 1
    auth_api._check_login_limit(key)
    auth_api._record_login_result(key, False)
    auth_api._record_login_result(key, True)
    assert key not in auth_api._login_failures


def test_security_headers_on_auth_and_api_responses():
    client = TestClient(app)
    response = client.get("/auth/config")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_restore_can_replace_corrupted_database_and_archive_original(tmp_path):
    database = tmp_path / "database.db"
    backup = tmp_path / "good.sqlite3"
    database.write_bytes(b"corrupted sqlite data")
    with sqlite3.connect(backup) as connection:
        connection.execute("CREATE TABLE restored (id INTEGER)")
        connection.execute("INSERT INTO restored VALUES (42)")
    previous = restore(backup, database, tmp_path / "backups", confirmed=True)
    assert previous is not None and previous.read_bytes() == b"corrupted sqlite data"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id FROM restored").fetchone() == (42,)


def test_password_update_revokes_other_browser_sessions(tmp_path, monkeypatch):
    from engine import auth
    from engine.auth import get_db as auth_get_db, hash_password

    monkeypatch.setattr(auth, "AUTH_MODE", "private")
    monkeypatch.setattr(auth_api, "AUTH_MODE", "private")
    database = make_engine(tmp_path)
    Base.metadata.create_all(database)
    with Session(database) as db:
        db.add(User(email="alice@example.org", password_hash=hash_password("old-password-123")))
        db.commit()

    def session_override():
        with Session(database) as db:
            yield db

    app.dependency_overrides[auth_get_db] = session_override
    try:
        browser_a = TestClient(app)
        browser_b = TestClient(app)
        credentials = {"email": "alice@example.org", "password": "old-password-123"}
        csrf_a = browser_a.post("/auth/login", json=credentials).json()["csrf_token"]
        browser_b.post("/auth/login", json=credentials)
        assert browser_b.get("/auth/me").status_code == 200
        result = browser_a.put("/auth/password", json={
            "current_password": "old-password-123", "new_password": "new-password-456"
        }, headers={"X-CSRF-Token": csrf_a})
        assert result.status_code == 200, result.text
        assert browser_a.get("/auth/me").status_code == 200
        assert browser_b.get("/auth/me").status_code == 401
        assert browser_b.post("/auth/login", json=credentials).status_code == 401
    finally:
        app.dependency_overrides.clear()
        database.dispose()


def test_unknown_schema_revision_refuses_downgrade(tmp_path):
    database = make_engine(tmp_path)
    with database.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE schema_migrations (version VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(40))"
        )
        connection.exec_driver_sql(
            "INSERT INTO schema_migrations VALUES ('2099_future_schema', '2099-01-01')"
        )
    with pytest.raises(RuntimeError, match="unsupported schema"):
        upgrade(database)
    database.dispose()
