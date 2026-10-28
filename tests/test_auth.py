"""Authorization and CSRF regression tests. Failure cases matter as much as success."""
import sqlite3
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, create_user, hash_token, utc_now_naive
from app.database import Base
from app.main import app
from app.models import AuthSession, SecurityEvent, Supplier, User
from tests.conftest import login_as


def test_anonymous_cannot_read_financial_data(client):
    visitor = TestClient(app)
    assert visitor.get("/", follow_redirects=False).headers["location"] == "/login"
    for path in ("/api/suppliers", "/api/invoices", "/api/audit", "/api/auth/me"):
        assert visitor.get(path).status_code == 401
    assert visitor.post("/api/suppliers", json={"name":"X", "bank_account":"ABCDE"}).status_code == 401
    assert visitor.get("/health").status_code == 200


def test_login_requires_csrf_and_correct_password(client):
    visitor = TestClient(app)
    assert visitor.post("/login", data={"username": "admin", "password": "bad"}).status_code == 403
    visitor.get("/login")
    invalid = visitor.post("/login", data={"username":"admin", "password":"wrong_password",
                                          "csrf_token":visitor.cookies.get("invoiceshield_login_csrf")})
    assert invalid.status_code == 200
    assert "Неверный логин" in invalid.text
    assert visitor.get("/api/invoices").status_code == 401


def test_csrf_blocks_html_and_api_writes(client):
    from tests.test_api import supplier
    body = {"name": "ООО Защита", "bank_account": "ABCD-12345"}
    assert client.post("/api/suppliers", json=body, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.post("/api/suppliers", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/web/suppliers", data={**body, "csrf_token": "wrong"}).status_code == 403
    assert client.post("/web/suppliers", data=body).status_code == 403
    assert client.get("/api/suppliers").json() == []
    s = supplier(client)
    assert client.post("/web/invoices", data={"supplier_id": s["id"]}).status_code == 403


def test_analyst_cannot_manage_suppliers_or_read_audit(client):
    from tests.test_api import invoice, supplier
    s = supplier(client)
    with Session(client.test_engine) as db:
        create_user(db, "analyst", "secure_test_password_456", "analyst")
    analyst = TestClient(app)
    token = login_as(analyst, "analyst", "secure_test_password_456")
    analyst.headers.update({"X-CSRF-Token": token})
    assert analyst.get("/").status_code == 200
    assert "Администратор" not in analyst.get("/").text
    assert "Добавлять поставщиков может только администратор" in analyst.get("/").text
    assert analyst.get("/api/suppliers").status_code == 200
    assert analyst.get("/api/audit").status_code == 403
    assert analyst.post("/api/suppliers", json={"name":"ООО Нет", "bank_account":"RU99999"}).status_code == 403
    assert analyst.post("/web/suppliers", data={"name":"ООО Нет", "bank_account":"RU99999", "csrf_token":token}).status_code == 403
    assert invoice(analyst, s["id"]).status_code == 201


def test_logout_revokes_server_side_session(client):
    token = client.cookies.get(SESSION_COOKIE)
    assert token
    with Session(client.test_engine) as db:
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    assert client.post("/logout", data={"csrf_token":"bad"}).status_code == 403
    assert client.get("/api/invoices").status_code == 200
    response = client.post("/logout", data={"csrf_token":client.csrf_token}, follow_redirects=False)
    assert response.status_code == 303
    assert client.get("/api/invoices").status_code == 401
    # An attacker holding the old cookie cannot reuse the revoked session.
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/invoices").status_code == 401


def test_expired_session_denied(client):
    token = client.cookies.get(SESSION_COOKIE)
    with Session(client.test_engine) as db:
        row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
        row.expires_at = utc_now_naive() - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/invoices").status_code == 401


def test_cookie_flags_and_csp(client):
    r = client.get("/")
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["Cache-Control"] == "no-store"
    r = TestClient(app).get("/login")
    assert "HttpOnly" in r.headers["set-cookie"]
    assert "SameSite=strict" in r.headers["set-cookie"]


def test_critical_actions_have_user_security_audit(client):
    from tests.test_api import invoice, supplier
    s = supplier(client)
    invoice(client, s["id"])
    with Session(client.test_engine) as db:
        events = list(db.scalars(select(SecurityEvent).order_by(SecurityEvent.id)).all())
    assert [e.event for e in events] == ["USER_CREATED", "LOGIN_SUCCESS", "SUPPLIER_CREATED", "INVOICE_CHECKED"]
    assert all("RU-1111-2222" not in e.detail for e in events)


def test_old_sqlite_supplier_survives_v02_table_creation(tmp_path):
    """0.1 database contains no auth tables; new schema must not drop the suppliers."""
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE suppliers (id INTEGER PRIMARY KEY, name VARCHAR(120), bank_account VARCHAR(64), created_at DATETIME)")
        conn.execute("INSERT INTO suppliers VALUES (7, 'ООО Старый', 'RU12345', '2026-10-28')")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert db.get(Supplier, 7).name == "ООО Старый"
        assert db.scalar(select(User.id).limit(1)) is None
    engine.dispose()
