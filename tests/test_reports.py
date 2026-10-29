"""Risk reporting: aggregates, filters, roles, spreadsheet safety, and privacy."""
from io import StringIO
import csv

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import create_user
from app.main import app
from tests.conftest import login_as
from tests.test_api import invoice, supplier


def sample(client):
    one = supplier(client, name="ООО Тест", bank="RU-1111-2222")
    two = supplier(client, name="ООО Другой", bank="RU-3333-4444")
    assert invoice(client, one["id"], number="LOW-1").status_code == 201
    assert invoice(client, one["id"], number="HIGH-1", bank="CHANGED").status_code == 201
    assert invoice(client, two["id"], number="MED-1", amount="1500000.00", bank="RU-3333-4444").status_code == 201
    return one, two


def test_summary_aggregates_amounts_and_risk_and_cases(client):
    sample(client)
    r = client.get("/api/analytics/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 3
    assert data["amount_rub"] == "1800000.00"
    assert data["risky_amount_rub"] == "1650000.00"
    assert data["risk_levels"] == {"LOW": 1, "MEDIUM": 1, "HIGH": 1}
    assert data["incident_statuses"]["OPEN"] == 2


def test_supplier_and_risk_filters(client):
    one, two = sample(client)
    assert client.get(f"/api/analytics/summary?supplier_id={one['id']}").json()["count"] == 2
    assert client.get(f"/api/analytics/summary?supplier_id={two['id']}&risk_level=HIGH").json()["count"] == 0
    assert client.get("/api/analytics/summary?risk_level=HIGH").json()["count"] == 1
    assert client.get("/api/analytics/summary?risk_level=MEDIUM").json()["amount_rub"] == "1500000.00"


def test_issued_date_filters_are_inclusive_and_empty_ok(client):
    sample(client)
    assert client.get("/api/analytics/summary?from_date=2026-10-28&to_date=2026-10-28").json()["count"] == 3
    assert client.get("/api/analytics/summary?from_date=2026-10-29").json()["count"] == 0
    assert client.get("/api/analytics/summary?to_date=2026-10-27").json()["count"] == 0


def test_bad_filters_return_validation_error(client):
    for query in ("from_date=2026-11-01&to_date=2026-10-28", "risk_level=INVALID",
                  "from_date=notadate", "supplier_id=-1"):
        assert client.get("/api/analytics/summary?" + query).status_code == 422
    assert client.get("/analytics?risk_level=INVALID").status_code == 422


def test_analytics_html_and_no_data(client):
    r = client.get("/analytics")
    assert r.status_code == 200
    assert "Риски по поставщикам" in r.text
    assert "Нет счетов" in r.text
    assert "Экспорт CSV" in r.text
    assert '/analytics' in client.get('/').text


def test_analytics_html_escapes_supplier_names(client):
    supplier(client, name="<script>alert('x')</script>")
    r = client.get("/analytics")
    assert "<script>alert('x')</script>" not in r.text


def test_export_is_admin_only_and_no_bank_account(client):
    sample(client)
    r = client.get("/api/analytics/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["Cache-Control"] == "no-store"
    contents = r.content.decode("utf-8-sig")
    assert "HIGH-1" in contents and "MED-1" in contents
    assert "RU11112222" not in contents and "CHANGED" not in contents
    assert len(list(csv.reader(StringIO(contents)))) == 4
    with Session(client.test_engine) as db:
        create_user(db, "analyst", "secure_test_password_456", "analyst")
    analyst = TestClient(app)
    login_as(analyst, "analyst", "secure_test_password_456")
    assert analyst.get("/analytics").status_code == 200
    assert "Экспорт CSV" not in analyst.get("/analytics").text
    assert analyst.get("/api/analytics/summary").status_code == 200
    assert analyst.get("/api/analytics/export.csv").status_code == 403


def test_anonymous_access_and_no_cache(client):
    anonymous = TestClient(app)
    assert anonymous.get("/analytics", follow_redirects=False).status_code == 303
    assert anonymous.get("/api/analytics/summary").status_code == 401
    assert anonymous.get("/api/analytics/export.csv").status_code == 401
    assert client.get("/analytics").headers["Cache-Control"] == "no-store"


def test_csv_formula_escape_on_untrusted_names(client):
    s = supplier(client, name='=HYPERLINK("https://example.test")')
    invoice(client, s["id"], number="+SUM(1,2)")
    content = client.get("/api/analytics/export.csv").content.decode("utf-8-sig")
    values = list(csv.reader(StringIO(content)))
    assert values[1][1].startswith("'+")
    assert values[1][2].startswith("'=")


def test_csv_has_no_data_rows_for_empty_result(client):
    sample(client)
    content = client.get("/api/analytics/export.csv?risk_level=HIGH&to_date=2026-10-27").content.decode("utf-8-sig")
    assert len(list(csv.reader(StringIO(content)))) == 1


def test_report_above_limit_fails_instead_of_truncating(client, monkeypatch):
    from app.services import analytics
    monkeypatch.setattr(analytics, "MAX_REPORT_ROWS", 2)
    sample(client)
    assert client.get("/api/analytics/summary").status_code == 413
    assert client.get("/api/analytics/export.csv").status_code == 413
    assert client.get("/analytics").status_code == 413
