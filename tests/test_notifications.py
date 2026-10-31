from unittest.mock import Mock, patch
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from engine.email_service import encrypt_secret, decrypt_secret, send_email
from engine.notifications_api import public_settings


def test_credential_encryption(monkeypatch):
    monkeypatch.setenv('SMTP_ENCRYPTION_KEY', Fernet.generate_key().decode())
    encrypted = encrypt_secret('secret-password')
    assert 'secret-password' not in encrypted
    assert decrypt_secret(encrypted) == 'secret-password'


def test_missing_key_rejects_encryption(monkeypatch):
    monkeypatch.delenv('SMTP_ENCRYPTION_KEY', raising=False)
    with pytest.raises(ValueError):
        encrypt_secret('abc')


def test_public_settings_never_returns_secret():
    settings = SimpleNamespace(enabled=True, recipient_email='test@example.com', smtp_host='mail.example.com',
                               smtp_port=587, smtp_security='starttls', smtp_username='test',
                               smtp_password_encrypted='sensitive', from_email='test@example.com', cooldown_hours=24)
    data = public_settings(settings)
    assert data['has_password'] is True
    assert 'smtp_password_encrypted' not in data


def test_send_uses_starttls(monkeypatch):
    monkeypatch.setenv('SMTP_ENCRYPTION_KEY', Fernet.generate_key().decode())
    settings = SimpleNamespace(smtp_security='starttls', smtp_host='mail.example.com', smtp_port=587,
                               smtp_username='test', smtp_password_encrypted=encrypt_secret('secret'),
                               from_email='test@example.com')
    with patch('engine.email_service.smtplib.SMTP') as smtp_cls:
        client = smtp_cls.return_value.__enter__.return_value
        send_email(settings, 'user@example.com', 'Test', 'Hello')
        client.starttls.assert_called_once()
        client.login.assert_called_once_with('test', 'secret')
        client.send_message.assert_called_once()
