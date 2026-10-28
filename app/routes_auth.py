"""Browser login/logout and the authenticated user's CSRF bootstrap endpoint."""
import hmac
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    LOGIN_CSRF_COOKIE, check_password, clear_session_cookie,
    lookup_identity, new_session, require_api_user, require_web_user,
    revoke_session, set_session_cookie, verify_csrf,
)
from app.config import COOKIE_SECURE
from app.database import get_db
from app.models import SecurityEvent, User

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def login_page(request: Request, error: str = "") -> HTMLResponse:
    csrf_token = secrets.token_urlsafe(32)
    response = templates.TemplateResponse(
        request=request, name="login.html", context={"csrf_token": csrf_token, "error": error}
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
    user = db.scalar(select(User).where(User.username == username)) if username else None
    if user is None or not user.is_active or not check_password(password, user.password_hash):
        db.add(SecurityEvent(user_id=user.id if user else None,
                             event="LOGIN_FAILURE", detail="Неверные учётные данные"))
        db.commit()
        return login_page(request, "Неверный логин или пароль")
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
