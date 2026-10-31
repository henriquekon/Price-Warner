"""Per-user notification settings and SMTP connection checks."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from data.models import NotificationSettings, SessionLocal, User
from engine.auth import current_user
from engine.email_service import encrypt_secret, send_email

router = APIRouter(prefix='/notifications', tags=['notifications'])


def get_db():
    with SessionLocal() as db:
        yield db


class SettingsUpdate(BaseModel):
    enabled: bool = False
    recipient_email: EmailStr | None = None
    smtp_host: str = Field(default='', max_length=253)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: str = 'starttls'
    smtp_username: str = Field(default='', max_length=320)
    smtp_password: str | None = Field(default=None, max_length=1024)
    from_email: EmailStr | None = None
    cooldown_hours: int = Field(default=24, ge=1, le=720)

    @field_validator('smtp_security')
    @classmethod
    def security_mode(cls, value):
        if value not in {'starttls', 'ssl'}:
            raise ValueError('smtp_security must be starttls or ssl')
        return value


def public_settings(settings):
    if settings is None:
        return {'enabled': False, 'recipient_email': None, 'smtp_host': '', 'smtp_port': 587,
                'smtp_security': 'starttls', 'smtp_username': '', 'has_password': False,
                'from_email': None, 'cooldown_hours': 24}
    return {'enabled': settings.enabled, 'recipient_email': settings.recipient_email,
            'smtp_host': settings.smtp_host, 'smtp_port': settings.smtp_port,
            'smtp_security': settings.smtp_security, 'smtp_username': settings.smtp_username,
            'has_password': bool(settings.smtp_password_encrypted),
            'from_email': settings.from_email, 'cooldown_hours': settings.cooldown_hours}


@router.get('/settings')
def get_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return public_settings(db.get(NotificationSettings, user.id))


@router.put('/settings')
def put_settings(payload: SettingsUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = db.get(NotificationSettings, user.id)
    if settings is None:
        settings = NotificationSettings(user_id=user.id)
        db.add(settings)
    if payload.enabled and not all([payload.smtp_host, payload.recipient_email, payload.from_email]):
        raise HTTPException(422, 'SMTP host, sender and recipient are required to enable email')
    settings.enabled = payload.enabled
    settings.recipient_email = str(payload.recipient_email) if payload.recipient_email else None
    settings.smtp_host = payload.smtp_host.strip()
    settings.smtp_port = payload.smtp_port
    settings.smtp_security = payload.smtp_security
    settings.smtp_username = payload.smtp_username.strip()
    settings.from_email = str(payload.from_email) if payload.from_email else None
    settings.cooldown_hours = payload.cooldown_hours
    if payload.smtp_password is not None:
        if payload.smtp_password:
            try:
                settings.smtp_password_encrypted = encrypt_secret(payload.smtp_password)
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from exc
        else:
            settings.smtp_password_encrypted = None
    if settings.enabled and settings.smtp_username and not settings.smtp_password_encrypted:
        raise HTTPException(422, 'SMTP password required for authenticated SMTP')
    db.commit()
    return public_settings(settings)


@router.post('/test')
def test_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    settings = db.get(NotificationSettings, user.id)
    if not settings or not all([settings.smtp_host, settings.recipient_email, settings.from_email]):
        raise HTTPException(400, 'Configure SMTP settings before testing')
    try:
        send_email(settings, settings.recipient_email, 'Price-Warner SMTP test',
                   'Your Price-Warner email settings are working.')
    except Exception as exc:
        # Never expose passwords, internal addresses, or mail server errors to clients.
        import logging
        logging.getLogger(__name__).warning('SMTP test failed for user %s: %s', user.id, type(exc).__name__)
        raise HTTPException(502, 'SMTP test failed. Check server logs and your settings.') from exc
    return {'message': 'Test email sent'}
