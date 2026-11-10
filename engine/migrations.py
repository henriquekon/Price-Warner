"""Idempotent, versioned SQLite upgrades for the Price-Warner schema."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from data.models import Base, Monitoring, Product, User, engine

REVISION_COLUMNS = "2026_11_09_01_legacy_columns"
REVISION_INDEXES = "2026_11_09_02_lookup_indexes"
REVISIONS = (REVISION_COLUMNS, REVISION_INDEXES)

LEGACY_COLUMNS = {
    "products": {
        "image_url": "VARCHAR(1024)",
        "last_error": "VARCHAR(500)",
    },
    "price_history": {
        "availability": "VARCHAR(50)",
        "strategy_used": "VARCHAR(100)",
    },
    "users": {
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
    },
}


def _revision_columns(connection):
    inspector = inspect(connection)
    for table, required in LEGACY_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column, definition in required.items():
            if column not in existing:
                connection.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')


def _revision_indexes(connection):
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_price_history_product_fetched "
        "ON price_history (product_id, fetched_at)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_monitorings_user_active "
        "ON monitorings (user_id, is_active)"
    )


def applied_revisions(database_engine: Engine | None = None) -> list[str]:
    target = database_engine if database_engine is not None else engine
    with target.connect() as connection:
        if not inspect(connection).has_table("schema_migrations"):
            return []
        return list(connection.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars())


def upgrade(database_engine: Engine | None = None) -> None:
    target = database_engine if database_engine is not None else engine
    if target.dialect.name != "sqlite":
        raise RuntimeError("Versioned upgrades currently support SQLite only")

    old_tables = set(inspect(target).get_table_names())
    known_history = applied_revisions(target)
    unexpected = set(known_history) - set(REVISIONS)
    if unexpected:
        raise RuntimeError(f"Database has unsupported schema revisions: {sorted(unexpected)}")

    Base.metadata.create_all(target)
    with target.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(40) NOT NULL)"
        )
        history = set(connection.execute(text("SELECT version FROM schema_migrations")).scalars())
        for revision, action in (
            (REVISION_COLUMNS, _revision_columns),
            (REVISION_INDEXES, _revision_indexes),
        ):
            if revision in history:
                continue
            action(connection)
            connection.execute(
                text("INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :at)"),
                {"version": revision, "at": datetime.now(timezone.utc).isoformat()},
            )

    with Session(target) as db:
        local = db.scalar(select(User).where(User.email == "local@price-warner.invalid"))
        if local is None and (os.getenv("AUTH_MODE", "local").lower() == "local" or
                              ("products" in old_tables and "monitorings" not in old_tables)):
            local = User(email="local@price-warner.invalid", password_hash=None, is_admin=False)
            db.add(local)
            db.flush()
        if local is not None and "products" in old_tables and "monitorings" not in old_tables:
            for product in db.scalars(select(Product)).all():
                db.add(Monitoring(user_id=local.id, product_id=product.id,
                                  interval=product.interval,
                                  target_drop_percentage=product.target_drop_percentage,
                                  is_active=product.is_active))
        db.commit()


if __name__ == "__main__":
    upgrade()
    for revision in applied_revisions():
        print(revision)
