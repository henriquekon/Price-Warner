"""Non-destructive initial upgrade of Stage 2 SQLite databases."""
from sqlalchemy import select
from data.models import Base, Monitoring, Product, SessionLocal, User, engine


def upgrade():
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        local = db.scalar(select(User).where(User.email == "local@price-warner.invalid"))
        if local is None:
            local = User(email="local@price-warner.invalid", password_hash=None, is_admin=False)
            db.add(local)
            db.flush()
        monitored_ids = set(db.scalars(select(Monitoring.product_id).where(Monitoring.user_id == local.id)).all())
        for product in db.scalars(select(Product)).all():
            if product.id not in monitored_ids:
                db.add(Monitoring(user_id=local.id, product_id=product.id,
                                  interval=product.interval,
                                  target_drop_percentage=product.target_drop_percentage,
                                  is_active=product.is_active))
