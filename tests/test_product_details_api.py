"""Product details remain private and settings are per account."""
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from data.models import Base, Monitoring, PriceHistory, Product, Store, User
from engine.auth import current_user, get_db
from main import app


def test_details_and_settings_are_user_scoped():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        db.add_all([User(id=1, email='first@example.test'), User(id=2,email='second@example.test'), Store(id='kabum', name='KaBuM')])
        db.flush()
        db.add_all([Product(id=1,name='One',url='https://www.kabum.com.br/produto/1',store_id='kabum'),Product(id=2,name='Two',url='https://www.kabum.com.br/produto/2',store_id='kabum')])
        db.flush()
        db.add_all([Monitoring(user_id=1,product_id=1,interval=30), Monitoring(user_id=2,product_id=1,interval=120),Monitoring(user_id=2,product_id=2)])
        db.add_all([PriceHistory(product_id=1,price=120,fetched_at=datetime(2026,1,1)),PriceHistory(product_id=1,price=100,fetched_at=datetime(2026,1,2))])

    def override_db():
        with sessions() as db:
            yield db
    def override_user():
        with sessions() as db:
            yield db.get(User,1)
    app.dependency_overrides[get_db]=override_db
    app.dependency_overrides[current_user]=override_user
    try:
        with TestClient(app) as client:
            details=client.get('/products/1/details')
            assert details.status_code==200
            assert [row['price'] for row in details.json()['history']]==[120,100]
            assert client.get('/products/2/details').status_code==404
            assert client.patch('/products/2/monitoring',json={'interval':60,'target_drop_percentage':10,'is_active':False}).status_code==404
            assert client.patch('/products/1/monitoring',json={'interval':0,'target_drop_percentage':10,'is_active':True}).status_code==422
            assert client.patch('/products/1/monitoring',json={'interval':60,'target_drop_percentage':0,'is_active':True}).status_code==422
            saved=client.patch('/products/1/monitoring',json={'interval':60,'target_drop_percentage':15,'is_active':False})
            assert saved.status_code==200
            assert saved.json()['interval']==60
            assert saved.json()['is_active'] is False
            assert client.get('/products/1/details').json()['target_drop_percentage']==15
        with sessions() as db:
            own=db.query(Monitoring).filter_by(user_id=1,product_id=1).one()
            other=db.query(Monitoring).filter_by(user_id=2,product_id=1).one()
            assert (own.interval,own.target_drop_percentage,own.is_active)==(60,15,False)
            assert other.interval==120 and other.is_active is True
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
