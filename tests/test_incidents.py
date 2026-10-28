"""Investigation workflow, RBAC, CSRF, version conflicts and migration regression."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import create_user
from app.main import app
from tests.conftest import login_as
from tests.test_api import invoice, supplier


def high_case(client):
    s = supplier(client)
    response = invoice(client, s["id"], bank="RU-CHANGED-ACCOUNT")
    assert response.status_code == 201
    cases = client.get("/api/incidents").json()
    assert len(cases) == 1
    return cases[0]


def test_high_and_medium_create_incidents_low_does_not(client):
    s = supplier(client)
    invoice(client, s["id"], number="LOW")
    invoice(client, s["id"], number="MED", amount="1200000.00")
    invoice(client, s["id"], number="HIGH", bank="RU-CHANGED")
    cases = client.get("/api/incidents").json()
    assert len(cases) == 2
    assert {row["invoice_number"] for row in cases} == {"MED", "HIGH"}
    assert {row["status"] for row in cases} == {"OPEN"}
    assert all(row["version"] == 1 for row in cases)
    assert len(client.get("/api/incidents?status=OPEN").json()) == 2
    assert client.get("/api/incidents?status=RESOLVED").json() == []


def test_case_detail_and_html(client):
    case = high_case(client)
    detail = client.get(f"/api/incidents/{case['id']}")
    assert detail.status_code == 200
    assert detail.json()["events"][0]["event_type"] == "CREATED"
    assert "INC-1" in client.get("/incidents").text
    assert "Результаты проверки" in client.get(f"/incidents/{case['id']}").text
    assert client.get("/api/incidents/99999").status_code == 404
    assert client.get("/incidents/99999").status_code == 404


def test_status_workflow_and_history(client):
    case = high_case(client)
    cid = case["id"]
    path = f"/api/incidents/{cid}/status"
    wrong = client.post(path, json={"status": "RESOLVED", "version": 1})
    assert wrong.status_code == 409  # OPEN -> RESOLVED must first be IN_REVIEW
    a = client.post(path, json={"status": "IN_REVIEW", "version": 1})
    assert a.status_code == 200, a.text
    assert a.json()["version"] == 2
    b = client.post(path, json={"status": "RESOLVED", "version": 2})
    assert b.status_code == 200
    assert b.json()["status"] == "RESOLVED"
    assert client.get("/api/incidents?status=RESOLVED").json()[0]["id"] == cid
    assert client.post(path, json={"status": "IN_REVIEW", "version": 3}).status_code == 200
    events = client.get(f"/api/incidents/{cid}").json()["events"]
    assert [e["event_type"] for e in events] == ["CREATED", "STATUS_CHANGED", "STATUS_CHANGED", "STATUS_CHANGED"]


def test_stale_version_conflict_preserves_history(client):
    case = high_case(client)
    path = f"/api/incidents/{case['id']}/status"
    assert client.post(path, json={"status": "IN_REVIEW", "version": 1}).status_code == 200
    assert client.post(path, json={"status": "IN_REVIEW", "version": 1}).status_code == 409
    events = client.get(f"/api/incidents/{case['id']}").json()["events"]
    assert len(events) == 2


def test_admin_can_assign_active_user_and_unassign(client):
    case = high_case(client)
    with Session(client.test_engine) as db:
        analyst = create_user(db, "analyst", "secure_test_password_456", "analyst")
        uid = analyst.id
    url = f"/api/incidents/{case['id']}/assign"
    r = client.post(url, json={"assignee_id": uid, "version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["assignee_username"] == "analyst"
    assert r.json()["version"] == 2
    assert client.post(url, json={"assignee_id": 999999, "version": 2}).status_code == 422
    r = client.post(url, json={"assignee_id": None, "version": 2})
    assert r.status_code == 200
    assert r.json()["assignee_username"] is None


def test_analyst_can_comment_and_change_status_but_not_assign(client):
    case = high_case(client)
    with Session(client.test_engine) as db:
        create_user(db, "analyst", "secure_test_password_456", "analyst")
    analyst = TestClient(app)
    token = login_as(analyst, "analyst", "secure_test_password_456")
    analyst.headers.update({"X-CSRF-Token": token})
    cid = case["id"]
    assert analyst.get("/api/incidents").status_code == 200
    assert analyst.post(f"/api/incidents/{cid}/assign",
                        json={"assignee_id": None, "version": 1}).status_code == 403
    assert analyst.post(f"/web/incidents/{cid}/assign", data={
        "csrf_token": token, "version": 1, "assignee_id": ""
    }).status_code == 403
    assert analyst.post(f"/api/incidents/{cid}/status", json={
        "status": "IN_REVIEW", "version": 1
    }).status_code == 200
    comment = analyst.post(f"/api/incidents/{cid}/comments", json={"comment": "Проверено"})
    assert comment.status_code == 201
    assert comment.json()["actor_username"] == "analyst"
    assert "Назначить исполнителя" not in analyst.get(f"/incidents/{cid}").text


def test_csrf_and_anonymous_guards(client):
    case = high_case(client)
    url = f"/api/incidents/{case['id']}/comments"
    assert client.post(url, json={"comment": "OK"}, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.post(f"/web/incidents/{case['id']}/comments", data={
        "comment": "OK", "csrf_token": "wrong"
    }).status_code == 403
    unauth = TestClient(app)
    assert unauth.get("/api/incidents").status_code == 401
    assert unauth.get("/incidents", follow_redirects=False).headers["location"] == "/login"
    assert unauth.get(f"/incidents/{case['id']}", follow_redirects=False).headers["location"] == "/login"
    assert unauth.post(url, json={"comment": "OK"}).status_code == 401
    assert unauth.post(f"/api/incidents/{case['id']}/status",
                       json={"status": "IN_REVIEW", "version": 1}).status_code == 401


def test_comment_xss_escaped_and_size_checked(client):
    case = high_case(client)
    path = f"/api/incidents/{case['id']}/comments"
    assert client.post(path, json={"comment": "  "}).status_code == 422
    assert client.post(path, json={"comment": "x" * 1001}).status_code == 422
    r = client.post(path, json={"comment": "<script>alert('x')</script>"})
    assert r.status_code == 201
    html = client.get(f"/incidents/{case['id']}").text
    assert "&lt;script&gt;alert" in html
    assert "<script>alert" not in html


def test_html_status_comment_and_redirect(client):
    case = high_case(client)
    cid = case["id"]
    r = client.post(f"/web/incidents/{cid}/status", data={
        "status": "IN_REVIEW", "version": 1, "csrf_token": client.csrf_token,
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "Статус изменён" in r.text
    r = client.post(f"/web/incidents/{cid}/comments", data={
        "comment": "Проверено вручную", "csrf_token": client.csrf_token,
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "Проверено вручную" in r.text
    r = client.post(f"/web/incidents/{cid}/status", data={
        "status": "RESOLVED", "version": 1, "csrf_token": client.csrf_token,
    }, follow_redirects=True)
    assert "Данные изменились" in r.text


def test_v03_backfill_keeps_old_records_and_is_idempotent(tmp_path):
    """Run exactly the documented migration command against an existing 0.2 database."""
    from sqlalchemy import create_engine
    from app.database import Base
    from app.models import Invoice, Supplier

    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    # Legacy schema: all 0.2 tables except new incident tables.
    legacy = [t for t in Base.metadata.sorted_tables if t.name not in {"incidents", "incident_events"}]
    Base.metadata.create_all(engine, tables=legacy)
    with Session(engine) as db:
        s = Supplier(name="ООО Старый", bank_account="RU-12345")
        db.add(s)
        db.flush()
        invoice = Invoice(supplier_id=s.id, invoice_number="OLD-002", amount_kopecks=123456,
                          bank_account="RU-CHANGED", issued_on="2026-10-28",
                          risk_score=70, risk_level="HIGH", findings=[])
        # sqlite DATE requires a Python date, not a string.
        from datetime import date
        invoice.issued_on = date(2026, 10, 28)
        db.add(invoice)
        db.commit()
    engine.dispose()

    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}"}
    root = Path(__file__).resolve().parents[1]
    for count in (1, 0):
        result = subprocess.run([sys.executable, "-m", "scripts.migrate_v03"],
                                cwd=root, env=env, check=True, capture_output=True, text=True)
        assert f"создано {count}" in result.stdout
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM incident_events").fetchone()[0] == 1
