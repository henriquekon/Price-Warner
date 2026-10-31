import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from data.models import AuthSession, SessionLocal, User

AUTH_MODE = os.getenv("AUTH_MODE", "local").strip().lower()
if AUTH_MODE not in {"local", "private", "public"}:
    raise RuntimeError("AUTH_MODE must be local, private, or public")
SESSION_COOKIE = "pw_session"
SESSION_DAYS = 7


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Password must contain 12 to 128 characters")
    salt = os.urandom(16)
    iterations = 600_000
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, iterations, salt_hex, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


def get_db():
    with SessionLocal() as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    if AUTH_MODE == "local":
        user = db.query(User).filter(User.email == "local@price-warner.invalid").first()
        if user is None:
            raise HTTPException(503, "Local account is not initialized")
        return user
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Authentication required")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    auth_session = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
    if not auth_session or auth_session.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        raise HTTPException(401, "Session expired or invalid")
    user = db.get(User, auth_session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "Inactive account")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), auth_session.csrf_token):
            raise HTTPException(403, "Invalid CSRF token")
    return user


def create_session(db: Session, user: User) -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_hex(32)
    db.add(AuthSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                       csrf_token=csrf_token,
                       expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=SESSION_DAYS)))
    db.commit()
    return token, csrf_token
