"""Security regression tests for server-side throttling and readiness."""
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.auth import LOGIN_CSRF_COOKIE, login_throttle_key
from app.main import app
from app.models import LoginThrottle, SecurityEvent


def post_login(visitor, username, password):
    visitor.get("/login")
    return visitor.post("/login", data={
        "username": username,
        "password": password,
        "csrf_token": visitor.cookies.get(LOGIN_CSRF_COOKIE),
    }, follow_redirects=False)


def test_login_throttled_after_five_failures_and_valid_password_denied(client):
    visitor = TestClient(app)
    for _ in range(4):
        failed = post_login(visitor, "admin", "incorrect-passphrase")
        assert failed.status_code == 200
        assert "Неверный логин" in failed.text
    blocked = post_login(visitor, "admin", "incorrect-passphrase")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "900"
    correct = post_login(visitor, "admin", "secure_test_password_123")
    assert correct.status_code == 429
    with Session(client.test_engine) as db:
        counter = db.get(LoginThrottle, login_throttle_key("admin", "testclient"))
        assert counter is not None and counter.failures == 5
        assert counter.blocked_until is not None


def test_success_clears_counter(client):
    visitor = TestClient(app)
    assert post_login(visitor, "admin", "wrong_password").status_code == 200
    assert post_login(visitor, "admin", "secure_test_password_123").status_code == 303
    with Session(client.test_engine) as db:
        assert db.get(LoginThrottle, login_throttle_key("admin", "testclient")) is None


def test_throttle_persists_across_clients_and_expires(client):
    a, b = TestClient(app), TestClient(app)
    for _ in range(5):
        post_login(a, "admin", "invalid-password")
    assert post_login(b, "admin", "secure_test_password_123").status_code == 429
    with Session(client.test_engine) as db:
        counter = db.get(LoginThrottle, login_throttle_key("admin", "testclient"))
        counter.window_started_at -= timedelta(minutes=16)
        counter.blocked_until -= timedelta(minutes=16)
        db.commit()
    assert post_login(b, "admin", "secure_test_password_123").status_code == 303


def test_unknown_account_is_throttled_without_user_leak(client):
    visitor = TestClient(app)
    for _ in range(4):
        response = post_login(visitor, "unknown_user", "incorrect-password")
        assert response.status_code == 200
        assert "Неверный логин или пароль" in response.text
    assert post_login(visitor, "unknown_user", "incorrect-password").status_code == 429
    with Session(client.test_engine) as db:
        events = db.scalars(select(SecurityEvent).where(SecurityEvent.event == "LOGIN_FAILURE")).all()
        assert len(events) == 5
        assert all("unknown_user" not in event.detail for event in events)


def test_distinct_source_does_not_share_throttle_counter(client):
    visitor = TestClient(app)
    for _ in range(5):
        post_login(visitor, "admin", "wrong-password")
    # Simulate a second remote address at the service layer. No untrusted
    # X-Forwarded-For header is consulted by the app.
    with Session(client.test_engine) as db:
        other, _ = auth.login_throttle_state(db, "admin", "192.0.2.22")
        assert other.failures == 0
        db.rollback()


def test_long_password_fails_before_argon2_and_no_login(client, monkeypatch):
    visitor = TestClient(app)
    def must_not_verify(*args, **kwargs):
        raise AssertionError("Argon2 should not run on unbounded input")
    monkeypatch.setattr("app.routes_auth.check_password", must_not_verify)
    response = post_login(visitor, "admin", "x" * 1025)
    assert response.status_code == 200
    assert "Неверный логин" in response.text


def test_readiness_and_browser_headers(client):
    ready = client.get("/ready")
    assert ready.json() == {"status": "ready", "version": "0.8.0"}
    assert ready.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert "Strict-Transport-Security" not in ready.headers
    assert client.get("/health").json() == {"status": "ok", "version": "0.8.0"}


def test_csrf_violations_not_counted_as_password_failures(client):
    visitor = TestClient(app)
    for _ in range(10):
        assert visitor.post("/login", data={"username": "admin", "password": "abc"}).status_code == 403
    with Session(client.test_engine) as db:
        assert db.scalar(select(LoginThrottle)) is None


def test_readiness_uses_generic_error_when_database_unavailable(client):
    from app.database import get_db

    class BrokenDatabase:
        def execute(self, _query):
            raise RuntimeError("database_password=should-never-leak")

    def broken_db():
        yield BrokenDatabase()

    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "База данных недоступна"}
        assert "should-never-leak" not in response.text
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_https_sets_hsts_but_http_does_not(client):
    visitor = TestClient(app, base_url="https://testserver")
    assert visitor.get("/health").headers["Strict-Transport-Security"] == "max-age=31536000"
    assert "Strict-Transport-Security" not in client.get("/health").headers
