from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import engine.auth as auth
import engine.auth_api as auth_api
from data.models import Base, User
from engine.auth import get_db as auth_db, hash_password
from engine.notifications_api import get_db as notifications_db
from main import app


def test_account_password_and_notification_settings(monkeypatch):
    monkeypatch.setattr(auth, 'AUTH_MODE', 'private')
    monkeypatch.setattr(auth_api, 'AUTH_MODE', 'private')
    monkeypatch.setenv('SMTP_ENCRYPTION_KEY', Fernet.generate_key().decode())
    with TemporaryDirectory() as directory:
        engine = create_engine(f"sqlite:///{Path(directory) / 'test.db'}", connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(User(email='owner@example.com', password_hash=hash_password('original-password-123')))
            db.commit()

        def test_db():
            with Session(engine) as db:
                yield db

        app.dependency_overrides[auth_db] = test_db
        app.dependency_overrides[notifications_db] = test_db
        try:
            client = TestClient(app)
            assert client.get('/notifications/settings').status_code == 401
            login = client.post('/auth/login', json={'email':'owner@example.com', 'password':'original-password-123'})
            assert login.status_code == 200
            headers = {'X-CSRF-Token':login.json()['csrf_token']}
            assert client.put('/auth/password', headers=headers, json={
                'current_password':'invalid-password-123', 'new_password':'updated-password-123'
            }).status_code == 400
            change = client.put('/auth/password', headers=headers, json={
                'current_password':'original-password-123', 'new_password':'updated-password-123'
            })
            assert change.status_code == 200, change.text
            assert client.post('/auth/login', json={'email':'owner@example.com', 'password':'original-password-123'}).status_code == 401
            assert client.post('/auth/login', json={'email':'owner@example.com', 'password':'updated-password-123'}).status_code == 200
            headers = {'X-CSRF-Token': client.get('/auth/csrf').json()['csrf_token']}
            payload = {
                'enabled':True, 'recipient_email':'owner@example.com', 'smtp_host':'smtp.example.com',
                'smtp_port':587, 'smtp_security':'starttls', 'smtp_username':'owner@example.com',
                'smtp_password':'test-password-123', 'from_email':'owner@example.com', 'cooldown_hours':24
            }
            assert client.put('/notifications/settings', json=payload).status_code == 403
            saved = client.put('/notifications/settings', headers=headers, json=payload)
            assert saved.status_code == 200, saved.text
            assert saved.json()['has_password'] is True
            assert 'smtp_password' not in saved.json()
            payload.pop('smtp_password')
            again = client.put('/notifications/settings', headers=headers, json=payload)
            assert again.status_code == 200 and again.json()['has_password']
            with patch('engine.notifications_api.send_email') as send:
                test = client.post('/notifications/test', headers=headers)
                assert test.status_code == 200, test.text
                send.assert_called_once()
        finally:
            app.dependency_overrides.clear()
