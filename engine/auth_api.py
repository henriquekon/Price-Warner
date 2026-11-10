import hashlib
import threading
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from data.models import AuthSession, User
from engine.auth import AUTH_MODE, SESSION_COOKIE, SESSION_DAYS, create_session, current_user, get_db, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])

LOGIN_FAILURE_LIMIT = 8
LOGIN_WINDOW_SECONDS = 15 * 60
_login_failures: dict[tuple[str, str], tuple[int, float]] = {}
_login_lock = threading.Lock()


def _login_key(request: Request, email: str) -> tuple[str, str]:
    return (request.client.host if request.client else "unknown", email)


def _check_login_limit(key: tuple[str, str]) -> None:
    now = time.monotonic()
    with _login_lock:
        count, expires_at = _login_failures.get(key, (0, 0.0))
        if expires_at <= now:
            _login_failures.pop(key, None)
            return
        if count >= LOGIN_FAILURE_LIMIT:
            raise HTTPException(429, "Too many failed login attempts", headers={
                "Retry-After": str(max(1, int(expires_at - now) + 1))
            })


def _record_login_result(key: tuple[str, str], succeeded: bool) -> None:
    now = time.monotonic()
    with _login_lock:
        if succeeded:
            _login_failures.pop(key, None)
            return
        count, expires_at = _login_failures.get(key, (0, 0.0))
        if expires_at <= now:
            count, expires_at = 0, now + LOGIN_WINDOW_SECONDS
        _login_failures[key] = (count + 1, expires_at)
        if len(_login_failures) > 4096:
            for stale in [item for item, (_count, expiry) in _login_failures.items() if expiry <= now]:
                _login_failures.pop(stale, None)
            while len(_login_failures) > 4096:
                _login_failures.pop(next(iter(_login_failures)))



class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


def set_cookie(response: Response, request: Request, token: str):
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/")


@router.get("/config")
def config():
    return {"mode": AUTH_MODE, "registration_enabled": AUTH_MODE == "public"}


@router.post("/register", status_code=201)
def register(credentials: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if AUTH_MODE != "public":
        raise HTTPException(403, "Registration disabled")
    user = User(email=str(credentials.email).lower(), password_hash=hash_password(credentials.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Email already registered") from exc
    token, csrf_token = create_session(db, user)
    set_cookie(response, request, token)
    return {"id": user.id, "email": user.email, "csrf_token": csrf_token}


@router.post("/login")
def login(credentials: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    if AUTH_MODE == "local":
        raise HTTPException(403, "Login not available in local mode")
    email = str(credentials.email).lower()
    key = _login_key(request, email)
    _check_login_limit(key)
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or not verify_password(credentials.password, user.password_hash):
        _record_login_result(key, False)
        raise HTTPException(401, "Invalid credentials")
    _record_login_result(key, True)
    token, csrf_token = create_session(db, user)
    set_cookie(response, request, token)
    return {"id": user.id, "email": user.email, "csrf_token": csrf_token}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin, "mode": AUTH_MODE}


@router.get("/csrf")
def csrf(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if AUTH_MODE == "local":
        return {"csrf_token": None}
    token = request.cookies.get(SESSION_COOKIE, "")
    auth_session = db.query(AuthSession).filter(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest(), AuthSession.user_id == user.id).first()
    if not auth_session:
        raise HTTPException(401, "Session expired")
    return {"csrf_token": auth_session.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(AuthSession).filter(AuthSession.token_hash == hashlib.sha256(token.encode()).hexdigest(), AuthSession.user_id == user.id).delete()
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"message": "Logged out"}

class PasswordChange(BaseModel):
    current_password: str = Field(min_length=12, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


@router.put('/password')
def change_password(payload: PasswordChange, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if AUTH_MODE == 'local':
        raise HTTPException(403, 'Password changes are unavailable in local mode')
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, 'Current password is incorrect')
    if payload.current_password == payload.new_password:
        raise HTTPException(400, 'New password must differ from current password')
    user.password_hash = hash_password(payload.new_password)
    token = request.cookies.get(SESSION_COOKIE, "")
    current_token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id, AuthSession.token_hash != current_token_hash
    ).delete(synchronize_session=False)
    db.commit()
    return {'message': 'Password updated'}
