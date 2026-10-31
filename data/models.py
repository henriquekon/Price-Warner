from datetime import datetime
from pathlib import Path
import os
from typing import List

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = Path(os.getenv("PRICE_WARNER_DATA_DIR", str(BASE_DIR)))
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "database.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1024), unique=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    target_drop_percentage: Mapped[float] = mapped_column(Float, default=10.0)
    history: Mapped[List["PriceHistory"]] = relationship(back_populates="product")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self):
        return f"<Product(name={self.name}, store={self.store_id})>"


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    availability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    strategy_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product: Mapped["Product"] = relationship(back_populates="history")


def init_db():
    Base.metadata.create_all(bind=engine)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Monitoring(Base):
    __tablename__ = "monitorings"
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    interval: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    target_drop_percentage: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    smtp_host: Mapped[str] = mapped_column(String(253), default="", nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    smtp_security: Mapped[str] = mapped_column(String(20), default="starttls", nullable=False)
    smtp_username: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    cooldown_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)


class NotificationEvent(Base):
    __tablename__ = "notification_events"
    __table_args__ = (UniqueConstraint("monitoring_id", "price_history_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    monitoring_id: Mapped[int] = mapped_column(ForeignKey("monitorings.id"), nullable=False)
    price_history_id: Mapped[int] = mapped_column(ForeignKey("price_history.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PriceCycleState(Base):
    """Per-monitoring reference and notification state, independent of shared history."""
    __tablename__ = "price_cycle_states"
    monitoring_id: Mapped[int] = mapped_column(ForeignKey("monitorings.id"), primary_key=True)
    first_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confirmed_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_alert_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovered_since_alert: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
