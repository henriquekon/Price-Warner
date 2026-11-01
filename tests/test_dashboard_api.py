"""Dashboard behavior with a dedicated test database."""
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from data.models import Base, Monitoring, PriceHistory, Product, Store, User
from engine.auth import current_user
from engine.dashboard_api import get_db
from main import app


def test_dashboard_exposes_user_specific_latest_price():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add_all([User(id=1,email='one@example.test'),User(id=2,email='two@example.test'),Store(id='kabum',name='KaBuM!')])
        db.flush()
        db.add_all([Product(id=1,name='Test product',url='https://www.kabum.com.br/produto/1',store_id='kabum'), Product(id=2,name='Private product',url='https://www.kabum.com.br/produto/2',store_id='kabum')])
        db.flush()
        db.add_all([Monitoring(user_id=1,product_id=1),Monitoring(user_id=2,product_id=2)])
        db.add_all([PriceHistory(product_id=1,price=100,fetched_at=datetime(2026,1,1)),PriceHistory(product_id=1,price=75,fetched_at=datetime(2026,1,2))])
        db.commit()
    def override_db():
        with session_factory() as db: yield db
    def override_user():
        with session_factory() as db: yield db.get(User,1)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = override_user
    try:
        with TestClient(app) as client:
            response=client.get('/dashboard')
        assert response.status_code == 200
        body=response.json()
        assert body['summary']['total']==1
        assert body['summary']['price_drops']==1
        assert body['products'][0]['price']==75
        assert body['products'][0]['price_change_percent']==-25
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
