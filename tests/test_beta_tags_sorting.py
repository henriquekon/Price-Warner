"""B1.2: per-user tags, title-based suggestions, filters, and global sorting."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data.models import Base, Monitoring, MonitoringTag, PriceHistory, Product, Store, Tag, User
from engine.auth import current_user, get_db
from engine.api import get_db as api_db
from main import app


def setup_database():
    db_engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    sessions = sessionmaker(bind=db_engine)
    with sessions.begin() as db:
        db.add_all([User(id=1, email='one@example.test'), User(id=2, email='two@example.test'),
                    Store(id='kabum', name='KaBuM!')])
    selected = {'user_id': 1}

    def override_db():
        with sessions() as db:
            yield db

    def override_user():
        with sessions() as db:
            yield db.get(User, selected['user_id'])

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[api_db] = override_db
    app.dependency_overrides[current_user] = override_user
    return db_engine, sessions, selected


def create(client, name, number, tags):
    return client.post('/products', json={
        'name': name, 'url': f'https://www.kabum.com.br/produto/{number}',
        'store_id': 'kabum', 'tags': tags, 'interval': 60, 'target_drop_percentage': 10,
    })


def test_tag_suggestions_learn_from_titles_and_users_are_isolated():
    db_engine, sessions, selected = setup_database()
    try:
        with TestClient(app) as client:
            assert create(client, 'Memória DDR4 8GB', 101, ['RAM', 'PC']).status_code == 201
            assert create(client, 'Memoria DDR5 16GB', 102, ['ram']).status_code == 201
            assert client.get('/tags').json() == ['PC', 'RAM']
            suggested = client.get('/tags/suggest', params={'name': 'Memória DDR5 32GB'}).json()
            assert suggested['recommended'] == ['RAM']
            assert suggested['tags'] == ['PC', 'RAM']
            assert client.get('/tags/suggest', params={'name': 'SSD NVMe'}).json()['recommended'] == []
            assert create(client, 'Memória DDR4 64GB', 103, []).status_code == 201
            # Autosuggestions are not forced by the server.
            third = client.get('/products').json()
            assert next(row for row in third if row['name'].endswith('64GB'))['tags'] == []
            selected['user_id'] = 2
            assert client.get('/tags').json() == []
            assert client.get('/tags/suggest', params={'name': 'Memoria DDR5'}).json()['recommended'] == []
            response = create(client, 'Memória DDR4 8GB', 101, ['Notebook'])
            assert response.status_code == 201
            assert [item['tags'] for item in client.get('/products').json()] == [['Notebook']]
            selected['user_id'] = 1
            assert sorted(item['name'] for item in client.get('/dashboard', params={'q': 'RAM'}).json()['products']) == [
                'Memoria DDR5 16GB', 'Memória DDR4 8GB']
            assert client.get('/dashboard', params={'q': 'Notebook'}).json()['pagination']['total'] == 0
    finally:
        app.dependency_overrides.clear()
        db_engine.dispose()


def test_edit_removes_tags_without_affecting_shared_product_or_other_account():
    db_engine, sessions, selected = setup_database()
    try:
        with TestClient(app) as client:
            first = create(client, 'Memoria RAM 16GB', 110, ['RAM', 'Computador'])
            assert first.status_code == 201
            product_id = first.json()['product_id']
            selected['user_id'] = 2
            assert create(client, 'Memoria RAM 16GB', 110, ['Trabalho']).status_code == 201
            selected['user_id'] = 1
            details = client.get(f'/products/{product_id}/details').json()
            assert details['tags'] == ['Computador', 'RAM']
            payload = {'interval': 90, 'target_drop_percentage': 15, 'is_active': True, 'tags': ['Upgrade', 'upgrade']}
            response = client.patch(f'/products/{product_id}/monitoring', json=payload)
            assert response.status_code == 200
            assert response.json()['tags'] == ['Upgrade']
            assert client.get(f'/products/{product_id}/details').json()['tags'] == ['Upgrade']
            assert client.get('/products/search', params={'q': 'Upgrade'}).json()[0]['id'] == product_id
            assert client.get('/dashboard', params={'q': 'Upgrade'}).json()['pagination']['total'] == 1
            selected['user_id'] = 2
            assert client.get(f'/products/{product_id}/details').json()['tags'] == ['Trabalho']
            assert client.get('/dashboard', params={'q': 'Upgrade'}).json()['pagination']['total'] == 0
            assert client.delete(f'/products/{product_id}').json()['product_deleted'] is False
            selected['user_id'] = 1
            with sessions() as db:
                own_monitoring = db.query(Monitoring).filter_by(user_id=1, product_id=product_id).one()
                assert db.query(MonitoringTag).filter_by(monitoring_id=own_monitoring.id).count() == 1
            assert client.delete(f'/products/{product_id}').json()['product_deleted'] is True
            with sessions() as db:
                assert db.query(MonitoringTag).count() == 0
                assert db.query(Tag).filter_by(user_id=1).count() >= 1
    finally:
        app.dependency_overrides.clear()
        db_engine.dispose()


def test_validation_and_pagination_with_global_price_and_change_ordering():
    db_engine, sessions, selected = setup_database()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        with TestClient(app) as client:
            assert create(client, 'Item no tags', 200, []).status_code == 201
            assert create(client, 'Budget SSD', 201, ['SSD']).status_code == 201
            assert create(client, 'Premium SSD', 202, ['SSD']).status_code == 201
            assert create(client, 'Midrange SSD', 203, ['SSD', 'Hardware']).status_code == 201
            assert create(client, 'Invalid', 205, ['a']).status_code == 422
            assert create(client, 'Invalid', 205, ['many'] * 13).status_code == 422
            with sessions.begin() as db:
                prices = {2: (300, 100), 3: (100, 90), 4: (80, 120)}
                for product_id, (previous, latest) in prices.items():
                    db.add(PriceHistory(product_id=product_id, price=previous, fetched_at=now-timedelta(hours=2)))
                    db.add(PriceHistory(product_id=product_id, price=latest, fetched_at=now-timedelta(hours=1)))
            # No history is always sorted last, for both directions.
            asc = client.get('/dashboard', params={'period': 'last', 'sort': 'price_asc', 'page_size': 5}).json()
            # IDs are generated in insertion order and should order by actual prices.
            sorted_ids = [item['id'] for item in asc['products']]
            assert sorted_ids == [3, 2, 4, 1]
            desc = client.get('/dashboard', params={'period': 'last', 'sort': 'price_desc'}).json()
            assert [item['price'] for item in desc['products']] == [120, 100, 90, None]
            drops = client.get('/dashboard', params={'period': 'last', 'sort': 'change_asc', 'q': 'SSD'}).json()
            assert [row['price_change_percent'] for row in drops['products']] == [-66.67, -10.0, 50.0]
            rises = client.get('/dashboard', params={'period': 'last', 'sort': 'change_desc', 'q': 'SSD'}).json()
            assert [row['price_change_percent'] for row in rises['products']] == [50.0, -10.0, -66.67]
            assert client.get('/dashboard', params={'sort': 'unexpected'}).status_code == 422
    finally:
        app.dependency_overrides.clear()
        db_engine.dispose()


def test_existing_monitoring_update_without_tags_keeps_existing_tags():
    db_engine, sessions, selected = setup_database()
    try:
        with TestClient(app) as client:
            identifier = create(client, 'HD 1TB', 51, ['Storage']).json()['product_id']
            response = client.patch(f'/products/{identifier}/monitoring', json={
                'interval': 30, 'target_drop_percentage': 12, 'is_active': False,
            })
            assert response.status_code == 200
            assert response.json()['tags'] == ['Storage']
    finally:
        app.dependency_overrides.clear()
        db_engine.dispose()


def test_new_tag_tables_create_without_changing_existing_product_rows():
    db_engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    try:
        previous_schema = [table for table in Base.metadata.tables.values()
                           if table.name not in {'tags', 'monitoring_tags'}]
        Base.metadata.create_all(db_engine, tables=previous_schema)
        sessions = sessionmaker(bind=db_engine)
        with sessions.begin() as db:
            db.add(User(id=1, email='before@example.test'))
            db.add(Store(id='kabum', name='KaBuM!'))
            db.add(Product(id=1, name='Existing product', url='https://www.kabum.com.br/produto/1', store_id='kabum'))
        Base.metadata.create_all(db_engine)
        with sessions() as db:
            assert db.get(Product, 1).name == 'Existing product'
            assert db.query(Tag).all() == []
            assert db.query(MonitoringTag).all() == []
    finally:
        db_engine.dispose()


def test_sorting_precedes_pages_and_missing_prices_sort_last():
    db_engine, sessions, selected = setup_database()
    try:
        with sessions.begin() as db:
            for number in range(1, 26):
                db.add(Product(id=number, name=f'Item {number}',
                               url=f'https://www.kabum.com.br/produto/{number}', store_id='kabum'))
                db.add(Monitoring(user_id=1, product_id=number))
                if number <= 24:
                    db.add(PriceHistory(product_id=number, price=number * 10,
                                        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None)))
        with TestClient(app) as client:
            first = client.get('/dashboard', params={'sort': 'price_desc', 'page_size': 20}).json()
            second = client.get('/dashboard', params={'sort': 'price_desc', 'page_size': 20, 'page': 2}).json()
            assert [row['price'] for row in first['products']] == [number * 10 for number in range(24, 4, -1)]
            assert [row['price'] for row in second['products']] == [40, 30, 20, 10, None]
            by_tag = client.get('/dashboard', params={'q': 'memoría'}).json()
            assert by_tag['pagination']['total'] == 0
    finally:
        app.dependency_overrides.clear()
        db_engine.dispose()
