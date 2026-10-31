import os
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from data.models import Base, Monitoring, Product, Store, User
from engine.api import product_response


def test_monitorings_are_unique_per_user():
    with tempfile.TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'test.db'}")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Store(id="kabum", name="Kabum"))
            a = User(email="a@example.com", password_hash="hash")
            b = User(email="b@example.com", password_hash="hash")
            session.add_all([a, b]); session.flush()
            product = Product(name="GPU", url="https://www.kabum.com.br/produto/1", store_id="kabum")
            session.add(product); session.flush()
            session.add_all([
                Monitoring(user_id=a.id, product_id=product.id, target_drop_percentage=10),
                Monitoring(user_id=b.id, product_id=product.id, target_drop_percentage=25),
            ])
            session.commit()
            rows_a = session.query(Product, Monitoring).join(Monitoring).filter(Monitoring.user_id == a.id).all()
            rows_b = session.query(Product, Monitoring).join(Monitoring).filter(Monitoring.user_id == b.id).all()
            assert len(rows_a) == len(rows_b) == 1
            assert product_response(*rows_a[0])["target_drop_percentage"] == 10
            assert product_response(*rows_b[0])["target_drop_percentage"] == 25
