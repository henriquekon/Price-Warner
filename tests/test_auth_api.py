from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import engine.auth as auth
import engine.auth_api as auth_api
from data.models import Base, Store, User
from engine.auth import hash_password
from engine.auth import get_db as auth_db
from engine.api import get_db as api_db
from main import app


def test_private_mode_isolates_monitorings(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "private")
    monkeypatch.setattr(auth_api, "AUTH_MODE", "private")
    with TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'test.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(Store(id="kabum", name="KaBuM"))
            db.add_all([User(email="a@example.com", password_hash=hash_password("sample-password-123")),
                        User(email="b@example.com", password_hash=hash_password("sample-password-123"))])
            db.commit()

        def get_test_db():
            with Session(engine) as db:
                yield db

        app.dependency_overrides[auth_db] = get_test_db
        app.dependency_overrides[api_db] = get_test_db
        try:
            a = TestClient(app)
            b = TestClient(app)
            assert a.get('/products').status_code == 401
            assert a.post('/auth/register', json={'email':'c@example.com','password':'sample-password-123'}).status_code == 403
            response_a = a.post('/auth/login', json={'email':'a@example.com','password':'sample-password-123'})
            response_b = b.post('/auth/login', json={'email':'b@example.com','password':'sample-password-123'})
            assert response_a.status_code == response_b.status_code == 200
            token_a = response_a.json()['csrf_token']
            token_b = response_b.json()['csrf_token']
            payload = {'name':'Example','url':'https://www.kabum.com.br/produto/123','store_id':'kabum'}
            assert a.post('/products', json=payload).status_code == 403
            # The test uses a temporary addon folder so the endpoint checks remain deterministic.
            import engine.api as api
            from unittest.mock import patch
            addon = Path(directory) / 'kabum.json'
            addon.write_text('{}')
            with patch.object(api, 'ADDONS_DIR', Path(directory)):
                result = a.post('/products', json=payload, headers={'X-CSRF-Token': token_a})
                assert result.status_code == 201, result.text
                assert b.get('/products').json() == []
                assert len(a.get('/products').json()) == 1
                second = b.post('/products', json=payload, headers={'X-CSRF-Token': token_b})
                assert second.status_code == 201, second.text
                assert a.post('/products', json=payload, headers={'X-CSRF-Token': token_a}).status_code == 409
                assert b.delete('/products/12345', headers={'X-CSRF-Token': token_b}).status_code == 404
            a.post('/auth/logout', headers={'X-CSRF-Token': token_a})
            assert a.get('/products').status_code == 401
        finally:
            app.dependency_overrides.clear()
