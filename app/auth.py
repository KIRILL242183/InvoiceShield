"""Local educational authentication: Argon2id, revocable sessions and CSRF tokens.

Session tokens are never stored in plaintext in the database. This does not
replace HTTPS, MFA or production security reviews.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import COOKIE_SECURE, SESSION_SECONDS
from app.database import get_db
from app.models import AuthSession, LoginThrottle, SecurityEvent, User

SESSION_COOKIE = "__Host-invoiceshield" if COOKIE_SECURE else "invoiceshield_session"
LOGIN_CSRF_COOKIE = "__Host-login_csrf" if COOKIE_SECURE else "invoiceshield_login_csrf"
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
LOGIN_FAILURE_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_BLOCK_SECONDS = 15 * 60
DUMMY_PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$YLQfokgdGTUeBYuUWxdl9g$Q4573RbCr07nODfY6/A/+2z2T0OO2kv63k1HgbMaWYU"  # verification work for unknown users
USERNAME_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{2,31}\Z")


def utc_now_naive() -> datetime:
    # SQLite returns naive datetimes even for DateTime(timezone=True).
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (VerificationError, VerifyMismatchError, ValueError):
        return False


def create_user(db: Session, username: str, password: str, role: str) -> User:
    username = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Логин: 3–32 символа, латинские строчные буквы, цифры, ._-; начинается с буквы")
    if role not in ("admin", "analyst"):
        raise ValueError("Роль должна быть admin или analyst")
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Пароль должен содержать от 12 до 1024 символов")
    if db.scalar(select(User.id).where(User.username == username)) is not None:
        raise ValueError("Такой пользователь уже существует")
    user = User(username=username, password_hash=PASSWORD_HASHER.hash(password), role=role)
    db.add(user)
    db.flush()
    db.add(SecurityEvent(user_id=user.id, event="USER_CREATED", detail=f"role={role}"))
    db.commit()
    db.refresh(user)
    return user


def login_throttle_key(username: str, remote_addr: str) -> str:
    """Pseudonymous per-account/per-address key."""
    return hashlib.sha256(f"{username}\0{remote_addr}".encode("utf-8")).hexdigest()


def lock_login_counter(db: Session, key: str) -> None:
    """Serialize check/update even when the counter row does not exist."""
    connection = db.connection()
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    elif dialect == "postgresql":
        lock_id = int.from_bytes(bytes.fromhex(key[:16]), "big", signed=True)
        connection.exec_driver_sql("SELECT pg_advisory_xact_lock(%s)", (lock_id,))


def login_throttle_state(db: Session, username: str, remote_addr: str) -> tuple[LoginThrottle, int]:
    """Call inside a DB transaction; commit or rollback to release the lock."""
    key = login_throttle_key(username, remote_addr)
    lock_login_counter(db, key)
    row = db.get(LoginThrottle, key)
    now = utc_now_naive()
    if row is None:
        row = LoginThrottle(key_hash=key, failures=0, window_started_at=now)
        db.add(row)
    elif (now - row.window_started_at).total_seconds() >= LOGIN_WINDOW_SECONDS:
        row.failures = 0
        row.window_started_at = now
        row.blocked_until = None
    remaining = max(0, int((row.blocked_until - now).total_seconds()) + 1) if row.blocked_until and row.blocked_until > now else 0
    return row, remaining


def record_failed_login(row: LoginThrottle) -> int:
    row.failures += 1
    if row.failures >= LOGIN_FAILURE_LIMIT:
        row.blocked_until = utc_now_naive() + timedelta(seconds=LOGIN_BLOCK_SECONDS)
        return LOGIN_BLOCK_SECONDS
    return 0


def new_session(db: Session, user: User) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    row = AuthSession(
        user_id=user.id, token_hash=hash_token(token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=utc_now_naive() + timedelta(seconds=SESSION_SECONDS),
    )
    db.add(row)
    db.add(SecurityEvent(user_id=user.id, event="LOGIN_SUCCESS", detail="Вход выполнен"))
    db.commit()
    db.refresh(row)
    return token, row


def revoke_session(db: Session, row: AuthSession) -> None:
    db.add(SecurityEvent(user_id=row.user_id, event="LOGOUT", detail="Выход из аккаунта"))
    db.delete(row)
    db.commit()


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
        secure=COOKIE_SECURE, samesite="strict", path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, secure=COOKIE_SECURE, httponly=True,
                           samesite="strict", path="/")


@dataclass(frozen=True)
class Identity:
    user: User
    session: AuthSession


def lookup_identity(request: Request, db: Session) -> Identity | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or len(token) > 256:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if row is None or row.expires_at <= utc_now_naive() or not row.user.is_active:
        return None
    return Identity(user=row.user, session=row)


def require_api_user(request: Request, db: Session = Depends(get_db)) -> Identity:
    identity = lookup_identity(request, db)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Необходимо войти в систему")
    return identity


def require_web_user(request: Request, db: Session = Depends(get_db)) -> Identity:
    identity = lookup_identity(request, db)
    if identity is None:
        # In POST handlers return 401 instead of redirecting to prevent accidental writes.
        raise HTTPException(status_code=401, detail="Необходимо войти в систему")
    return identity


def require_api_csrf(request: Request, identity: Identity = Depends(require_api_user)) -> Identity:
    verify_csrf(identity, request.headers.get("X-CSRF-Token", ""))
    return identity


def verify_csrf(identity: Identity, supplied: str) -> None:
    if not supplied or not hmac.compare_digest(identity.session.csrf_token, supplied):
        raise HTTPException(status_code=403, detail="Неверный CSRF-токен")


def ensure_admin(identity: Identity) -> None:
    if identity.user.role != "admin":
        raise HTTPException(status_code=403, detail="Доступ только для администратора")
