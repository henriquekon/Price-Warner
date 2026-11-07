"""Beta watchlist deletion, pagination and product-image regressions."""
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from data.models import (AlertMetadata, Base, Monitoring, NotificationEvent,
                         PriceCycleState, PriceHistory, Product, Store, User)
from engine.auth import current_user
from engine.api import get_db as product_db
from engine.dashboard_api import get_db as dashboard_db
from engine.scraper import AddonScraper
from engine.media import validate_product_image_url
from engine.addons.registry import load_addon
from main import app


def _client_database():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def test_removing_a_monitoring_keeps_other_accounts_and_shared_history():
    engine, sessions = _client_database()
    with sessions.begin() as db:
        db.add_all([User(id=1, email='a@example.test'), User(id=2, email='b@example.test'),
                    Store(id='kabum', name='KaBuM!')])
        db.add(Product(id=9, name='Graphics card', url='https://www.kabum.com.br/produto/9', store_id='kabum'))
        db.flush()
        db.add_all([Monitoring(id=11, user_id=1, product_id=9),
                    Monitoring(id=22, user_id=2, product_id=9),
                    PriceHistory(id=123, product_id=9, price=199.9, fetched_at=datetime.utcnow())])
        db.flush()
        db.add_all([NotificationEvent(id=111, monitoring_id=11, price_history_id=123, status='sent'),
                    NotificationEvent(id=222, monitoring_id=22, price_history_id=123, status='sent'),
                    PriceCycleState(monitoring_id=11, last_alert_price=199.9),
                    PriceCycleState(monitoring_id=22, last_alert_price=199.9)])
        db.flush()
        db.add_all([AlertMetadata(event_id=111, kind='first_drop'),
                    AlertMetadata(event_id=222, kind='first_drop')])

    def db_override():
        with sessions() as db:
            yield db

    def user_override():
        with sessions() as db:
            yield db.get(User, 1)

    app.dependency_overrides[product_db] = db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app) as client:
            assert client.delete('/products/404').status_code == 404
            response = client.delete('/products/9')
            assert response.status_code == 200, response.text
            assert response.json()['product_deleted'] is False
            assert client.delete('/products/9').status_code == 404
        with sessions() as db:
            assert db.get(Monitoring, 11) is None
            assert db.get(Monitoring, 22) is not None
            assert db.get(PriceCycleState, 11) is None
            assert db.get(PriceCycleState, 22) is not None
            assert db.get(NotificationEvent, 111) is None
            assert db.get(NotificationEvent, 222) is not None
            assert db.get(AlertMetadata, 111) is None
            assert db.get(AlertMetadata, 222) is not None
            assert db.get(Product, 9) is not None
            assert db.get(PriceHistory, 123) is not None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_dashboard_paginates_after_filters_and_keeps_global_summary():
    engine, sessions = _client_database()
    with sessions.begin() as db:
        db.add_all([User(id=1, email='a@example.test'), User(id=2, email='b@example.test'),
                    Store(id='kabum', name='KaBuM!')])
        for number in range(1, 48):
            db.add(Product(id=number, name=f'Product {number}',
                           url=f'https://www.kabum.com.br/produto/{number}', store_id='kabum'))
        db.flush()
        for number in range(1, 46):
            db.add(Monitoring(user_id=1, product_id=number, is_active=(number % 2 == 0)))
        db.add(Monitoring(user_id=2, product_id=46))

    def db_override():
        with sessions() as db:
            yield db

    def user_override():
        with sessions() as db:
            yield db.get(User, 1)

    app.dependency_overrides[dashboard_db] = db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app) as client:
            first = client.get('/dashboard').json()
            assert first['summary']['total'] == 45
            assert first['pagination'] == {'page': 1, 'page_size': 20, 'total': 45, 'pages': 3}
            assert len(first['products']) == 20
            second = client.get('/dashboard?page=2').json()
            assert len(second['products']) == 20
            third = client.get('/dashboard?page=3').json()
            assert len(third['products']) == 5
            assert not set(row['id'] for row in first['products']) & set(row['id'] for row in second['products'])
            active = client.get('/dashboard?status=active&page_size=10').json()
            assert active['pagination']['total'] == 22
            assert len(active['products']) == 10
            search = client.get('/dashboard?q=Product%2045').json()
            assert search['pagination']['total'] == 1
            assert search['products'][0]['id'] == 45
            assert search['summary']['total'] == 45
            assert client.get('/dashboard?page_size=101').status_code == 422
            assert client.get('/dashboard?page=0').status_code == 422
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_store_image_urls_are_restricted_to_declared_hosts():
    addon = load_addon(Path(__file__).resolve().parents[1] / 'addons' / 'kabum.json')
    good = 'https://images.kabum.com.br/produtos/fotos/123.png'
    assert validate_product_image_url(good, addon) == good
    assert validate_product_image_url('https://example.org/tracker.png', addon) is None
    assert validate_product_image_url('javascript:alert(1)', addon) is None
    assert validate_product_image_url('https://images.kabum.com.br:8443/path', addon) is None


def test_kabum_search_uses_addon_defined_page_parameters_without_network():
    addon_path = Path(__file__).resolve().parents[1] / 'addons' / 'kabum.json'
    import json
    import httpx
    rows = [{'name': f'GPU {i}', 'code': i + 100, 'priceWithDiscount': 200 + i,
             'image': f'{i}.jpg'} for i in range(20)]
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({'props': {'pageProps': {'data': {'catalogServer': {'data': rows}}}}})
            + '</script>')
    with AddonScraper(str(addon_path)) as scraper:
        with patch.object(scraper, '_make_request', return_value=httpx.Response(200, text=html)) as request:
            response = scraper.search_external_page('placa video', page=2, page_size=20)
        parsed = urlsplit(request.call_args.args[0])
        params = parse_qs(parsed.query)
        assert params['page_number'] == ['2']
        assert params['page_size'] == ['20']
        assert response['page'] == 2
        assert len(response['items']) == 20
        assert response['has_next'] is True
        assert response['items'][0]['image_url'].startswith('https://images.kabum.com.br/')


def test_last_monitoring_removes_product_and_its_price_history():
    engine, sessions = _client_database()
    with sessions.begin() as db:
        db.add_all([User(id=1, email='a@example.test'), Store(id='kabum', name='KaBuM!')])
        db.flush()
        db.add(Product(id=9, name='Only monitored item',
                       url='https://www.kabum.com.br/produto/9', store_id='kabum'))
        db.flush()
        db.add_all([Monitoring(id=11, user_id=1, product_id=9),
                    PriceHistory(id=123, product_id=9, price=149.9),
                    PriceCycleState(monitoring_id=11)])
        db.flush()
        db.add(NotificationEvent(id=111, monitoring_id=11, price_history_id=123, status='sent'))
        db.flush()
        db.add(AlertMetadata(event_id=111, kind='first_drop'))

    def override_db():
        with sessions() as db:
            yield db

    def override_user():
        with sessions() as db:
            yield db.get(User, 1)

    app.dependency_overrides[product_db] = override_db
    app.dependency_overrides[current_user] = override_user
    try:
        with TestClient(app) as client:
            response = client.delete('/products/9')
        assert response.status_code == 200
        assert response.json()['product_deleted'] is True
        with sessions() as db:
            assert db.get(Product, 9) is None
            assert db.get(Monitoring, 11) is None
            assert db.get(PriceHistory, 123) is None
            assert db.get(NotificationEvent, 111) is None
            assert db.get(AlertMetadata, 111) is None
            assert db.get(PriceCycleState, 11) is None
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
