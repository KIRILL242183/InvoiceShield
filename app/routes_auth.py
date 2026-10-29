"""Browser login/logout and the authenticated user's CSRF bootstrap endpoint."""
import hmac
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    DUMMY_PASSWORD_HASH, LOGIN_CSRF_COOKIE, check_password, clear_session_cookie,
    login_throttle_state, lookup_identity, new_session, record_failed_login,
    require_api_user, require_web_user,
    revoke_session, set_session_cookie, verify_csrf,
)
from app.config import COOKIE_SECURE
from app.database import get_db
from app.models import SecurityEvent, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def login_page(request: Request, error: str = "", *, status_code: int = 200) -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request, name="login.html", context={"csrf_token": csrf_token, "error": error},
        status_code=status_code,
    )
    response.set_cookie(
        LOGIN_CSRF_COOKIE, csrf_token, httponly=True, secure=COOKIE_SECURE,
        samesite="strict", max_age=10 * 60, path="/",
    )
    return response


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def get_login(request: Request, db: Session = Depends(get_db)):
    if lookup_identity(request, db):
        return RedirectResponse(url="/", status_code=303)
    return login_page(request)


@router.post("/login", include_in_schema=False)
def post_login(
    request: Request, username: str = Form(""), password: str = Form(""),
    csrf_token: str = Form(""), db: Session = Depends(get_db),
):
    browser_token = request.cookies.get(LOGIN_CSRF_COOKIE, "")
    if not browser_token or not csrf_token or not hmac.compare_digest(browser_token, csrf_token):
        # CSRF must be validated even on login to prevent login-CSRF attacks.
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Неверный CSRF-токен")
    username = username.strip().lower()
    if len(username) > 32 or len(password) > 1024:
        return login_page(request, "Неверный логин или пароль")
    remote_addr = request.client.host if request.client else "unknown"
    counter, wait_seconds = login_throttle_state(db, username, remote_addr)
    if wait_seconds:
        db.commit()
        response = login_page(request, "Слишком много попыток. Попробуйте позже.", status_code=429)
        response.headers["Retry-After"] = str(wait_seconds)
        return response
    user = db.scalar(select(User).where(User.username == username)) if username else None
    password_ok = check_password(password, user.password_hash if user and user.is_active else DUMMY_PASSWORD_HASH)
    if user is None or not user.is_active or not password_ok:
        db.add(SecurityEvent(user_id=user.id if user else None,
                             event="LOGIN_FAILURE", detail="Неверные учётные данные"))
        blocked_for = record_failed_login(counter)
        db.commit()
        if blocked_for:
            response = login_page(request, "Слишком много попыток. Попробуйте позже.", status_code=429)
            response.headers["Retry-After"] = str(blocked_for)
            return response
        return login_page(request, "Неверный логин или пароль")
    db.delete(counter)
    token, _ = new_session(db, user)
    response = RedirectResponse(url="/", status_code=303)
    set_session_cookie(response, token)
    response.delete_cookie(LOGIN_CSRF_COOKIE, secure=COOKIE_SECURE,
                           httponly=True, samesite="strict", path="/")
    return response


@router.post("/logout", include_in_schema=False)
def post_logout(
    csrf_token: str = Form(""), identity=Depends(require_web_user),
    db: Session = Depends(get_db),
):
    verify_csrf(identity, csrf_token)
    revoke_session(db, identity.session)
    response = RedirectResponse(url="/login", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/api/auth/me", tags=["Authentication"])
def auth_me(identity=Depends(require_api_user)):
    """Same-origin browser/API clients can read the CSRF token after login."""
    return {"username": identity.user.username, "role": identity.user.role,
            "csrf_token": identity.session.csrf_token}
