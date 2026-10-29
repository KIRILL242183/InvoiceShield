"""Release acceptance: synthetic PDF -> risk -> case -> analyst -> report."""
from io import BytesIO

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import create_user
from app.main import app
from app.models import Invoice, IncidentEvent, User
from app.version import APP_VERSION
from tests.conftest import login_as


def sample_pdf():
    stream = BytesIO()
    doc = canvas.Canvas(stream)
    for n, line in enumerate((
        "Invoice No: PORTFOLIO-100",
        "Total Due: 1,234,567.89",
        "Bank Account: DE89 3704 0044 0532 0130 00",
        "Date: 29/10/2026",
    )):
        doc.drawString(40, 700 - n * 24, line)
    doc.save()
    return stream.getvalue()


def test_complete_invoice_investigation_journey(client):
    with Session(client.test_engine) as db:
        create_user(db, "analyst", "analyst_demo_password_123", "analyst")
    resp = client.post("/api/suppliers", json={
        "name": "ООО Демонстрационный поставщик",
        "bank_account": "DE11111111111111111111",
    })
    assert resp.status_code == 201
    supplier_id = resp.json()["id"]

    preview = client.post("/pdf-import",
        files={"file": ("sample.pdf", sample_pdf(), "application/pdf")},
        data={"csrf_token": client.csrf_token})
    assert preview.status_code == 200
    for field in ("PORTFOLIO-100", "1234567.89", "DE89370400440532013000"):
        assert field in preview.text
    with Session(client.test_engine) as db:
        assert db.scalar(select(func.count()).select_from(Invoice)) == 0

    checked = client.post("/api/invoices", json={
        "supplier_id": supplier_id,
        "invoice_number": "PORTFOLIO-100",
        "amount_rub": "1234567.89",
        "bank_account": "DE89370400440532013000",
        "issued_on": "2026-10-29",
    })
    assert checked.status_code == 201
    assert checked.json()["risk_score"] == 100
    case = client.get("/api/incidents").json()[0]
    assert case["status"] == "OPEN"
    cid = case["id"]
    with Session(client.test_engine) as db:
        analyst_id = db.scalar(select(User.id).where(User.username == "analyst"))
    assigned = client.post(f"/api/incidents/{cid}/assign", json={
        "assignee_id": analyst_id, "version": 1,
    })
    assert assigned.status_code == 200
    assert assigned.json()["version"] == 2

    analyst = TestClient(app)
    analyst_csrf = login_as(analyst, "analyst", "analyst_demo_password_123")
    analyst.headers.update({"X-CSRF-Token": analyst_csrf})
    assert analyst.get("/api/analytics/summary").json()["count"] == 1
    assert analyst.get("/api/analytics/export.csv").status_code == 403
    assert analyst.post(f"/api/incidents/{cid}/assign", json={
        "assignee_id": None, "version": 2,
    }).status_code == 403
    assert analyst.post(f"/api/incidents/{cid}/status", json={
        "status": "IN_REVIEW", "version": 2,
    }).status_code == 200
    assert analyst.post(f"/api/incidents/{cid}/comments", json={
        "comment": "Связались с поставщиком по независимому каналу",
    }).status_code == 201
    assert analyst.post(f"/api/incidents/{cid}/status", json={
        "status": "RESOLVED", "version": 3,
    }).status_code == 200

    detail = client.get(f"/api/incidents/{cid}").json()
    assert detail["incident"]["status"] == "RESOLVED"
    assert len(detail["events"]) == 5
    report = client.get("/api/analytics/export.csv").content.decode("utf-8-sig")
    assert "PORTFOLIO-100" in report
    assert "DE89370400440532013000" not in report
    with Session(client.test_engine) as db:
        assert db.scalar(select(func.count()).select_from(IncidentEvent)) == 5


def test_release_anonymous_csrf_and_version(client):
    anon = TestClient(app)
    for endpoint in ("/api/invoices", "/api/incidents", "/api/analytics/summary"):
        assert anon.get(endpoint).status_code == 401
    assert client.post("/api/suppliers", json={
        "name": "ООО Пример", "bank_account": "DE12345678",
    }, headers={"X-CSRF-Token": ""}).status_code == 403
    assert client.get("/").headers["Cache-Control"] == "no-store"
    assert client.get("/health").json()["version"] == APP_VERSION
