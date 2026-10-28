"""Tests of realistic finance-domain behaviour and common invalid requests."""
from datetime import date


def supplier(client, name="ООО Тест", bank="RU-1111-2222"):
    result = client.post("/api/suppliers", json={"name": name, "bank_account": bank})
    assert result.status_code == 201, result.text
    return result.json()


def invoice(client, supplier_id, number="INV-001", amount="150000.00", bank="RU-1111-2222"):
    return client.post("/api/invoices", json={
        "supplier_id": supplier_id,
        "invoice_number": number,
        "amount_rub": amount,
        "bank_account": bank,
        "issued_on": "2026-10-28",
    })


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "version": "0.1.0"}


def test_supplier_create_and_bank_normalization(client):
    row = supplier(client, bank="ru 1111 2222")
    assert row["bank_account"] == "RU11112222"
    assert client.get("/api/suppliers").json()[0]["name"] == "ООО Тест"


def test_duplicate_supplier_is_conflict(client):
    supplier(client)
    result = client.post("/api/suppliers", json={
        "name": "ООО Тест", "bank_account": "RU-3333-4444"
    })
    assert result.status_code == 409


def test_low_risk_invoice(client):
    s = supplier(client)
    result = invoice(client, s["id"])
    assert result.status_code == 201, result.text
    data = result.json()
    assert data["risk_score"] == 0
    assert data["risk_level"] == "LOW"
    assert data["amount_rub"] == "150000.00"
    assert data["findings"] == []


def test_bank_account_switch_is_high_risk(client):
    s = supplier(client)
    data = invoice(client, s["id"], bank="RU-9999-8888").json()
    assert data["risk_score"] == 70
    assert data["risk_level"] == "HIGH"
    assert data["findings"][0]["code"] == "BANK_ACCOUNT_CHANGED"


def test_duplicate_invoice_number_for_same_supplier(client):
    s = supplier(client)
    assert invoice(client, s["id"]).status_code == 201
    second = invoice(client, s["id"], number="inv-001")
    assert second.status_code == 201
    assert second.json()["risk_score"] == 60
    assert second.json()["findings"][0]["code"] == "DUPLICATE_NUMBER"


def test_same_number_for_different_suppliers_not_duplicate(client):
    a = supplier(client, "ООО Альфа")
    b = supplier(client, "ООО Бета")
    invoice(client, a["id"])
    result = invoice(client, b["id"])
    assert result.json()["risk_score"] == 0


def test_large_amount_is_medium_risk(client):
    s = supplier(client)
    result = invoice(client, s["id"], amount="1000000.01")
    assert result.json()["risk_score"] == 35
    assert result.json()["risk_level"] == "MEDIUM"


def test_aggregate_capped_at_100(client):
    s = supplier(client)
    invoice(client, s["id"])
    result = invoice(client, s["id"], amount="1500000.00", bank="CHANGED")
    assert result.json()["risk_score"] == 100
    assert len(result.json()["findings"]) == 3


def test_unknown_supplier_returns_404(client):
    assert invoice(client, 9999).status_code == 404


def test_bad_amount_rejected(client):
    s = supplier(client)
    assert invoice(client, s["id"], amount="-10").status_code == 422
    assert invoice(client, s["id"], amount="10.001").status_code == 422


def test_audit_log_records_actions_without_bank_numbers(client):
    s = supplier(client)
    invoice(client, s["id"])
    events = client.get("/api/audit").json()
    assert [event["action"] for event in events] == ["INVOICE_CHECKED", "SUPPLIER_CREATED"]
    assert "RU-1111-2222" not in repr(events)


def test_homepage_and_forms(client):
    assert "InvoiceShield" in client.get("/").text
    result = client.post("/web/suppliers", data={
        "name": "ООО Пример", "bank_account": "RU1111ABCDE"
    }, follow_redirects=True)
    assert result.status_code == 200
    assert "ООО Пример" in result.text
    assert "Поставщик добавлен" in result.text


def test_html_form_add_invoice(client):
    s = supplier(client)
    result = client.post("/web/invoices", data={
        "supplier_id": str(s["id"]),
        "invoice_number": "HTML-1",
        "amount_rub": "55.50",
        "bank_account": "RU-1111-2222",
        "issued_on": date.today().isoformat(),
    }, follow_redirects=True)
    assert result.status_code == 200
    assert "HTML-1" in result.text
    assert "55.50" in result.text


def test_html_escapes_untrusted_supplier_name(client):
    supplier(client, name="<script>alert(42)</script>")
    text = client.get("/").text
    assert "&lt;script&gt;alert(42)&lt;/script&gt;" in text
    assert "<script>alert(42)</script>" not in text


def test_exact_large_amount_threshold_does_not_trigger(client):
    s = supplier(client)
    assert invoice(client, s["id"], amount="1000000.00").json()["risk_score"] == 0


def test_basic_security_response_headers(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
