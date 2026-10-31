from datetime import datetime
from pathlib import Path
import os
from typing import List

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database.db"
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
