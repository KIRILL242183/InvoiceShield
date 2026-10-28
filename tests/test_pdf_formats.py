"""Regression tests for parser ambiguity and Russian/English invoice layouts."""
from io import BytesIO

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice
from app.services.pdf_import import PdfRejected, extract_draft, parse_invoice_text


RUSSIAN = """Счёт на оплату № АБ-2026/15 от 29 октября 2026 г.
Получатель: ООО «Тест»
Итого к оплате: 1 234 567,89 руб.
Расчётный счёт: 40702810 0000 0000 0001
"""
ENGLISH = """Invoice No: INV-2026/04
Total Due: 1,234,567.89 RUB
Bank Account: DE89 3704 0044 0532 0130 00
Invoice Date: 29/10/2026
"""


def test_russian_invoice_header_with_written_month():
    result = parse_invoice_text(RUSSIAN)
    assert (result.invoice_number, result.amount_rub, result.bank_account, result.issued_on) == (
        "АБ-2026/15", "1234567.89", "40702810000000000001", "2026-10-29"
    )
    assert len(result.warnings) == 1


def test_english_invoice_with_us_separators_and_spaced_iban():
    result = parse_invoice_text(ENGLISH)
    assert (result.invoice_number, result.amount_rub, result.bank_account, result.issued_on) == (
        "INV-2026/04", "1234567.89", "DE89370400440532013000", "2026-10-29"
    )


@pytest.mark.parametrize(("value", "expected"), [
    ("1 000 000,50", "1000000.50"),
    ("1.000.000,50", "1000000.50"),
    ("1,000,000.50", "1000000.50"),
    ("12 345", "12345.00"),
    ("22,5", "22.50"),
    ("0,01", "0.01"),
    ("13.999,99", "13999.99"),
])
def test_supported_money_formats(value, expected):
    assert parse_invoice_text(f"К оплате: {value}").amount_rub == expected


@pytest.mark.parametrize("value", ["1,234", "1.234", "12 34", "0,00", "-2"])
def test_money_does_not_guess_incorrect_or_ambiguous_formats(value):
    assert parse_invoice_text(f"Итого: {value}").amount_rub == ""


def test_conflicting_totals_clears_amount_and_warns():
    result = parse_invoice_text("Total: 100.00\nTotal: 200.00")
    assert result.amount_rub == ""
    assert any("Неоднозначное" in warning and "сумма" in warning for warning in result.warnings)


def test_account_with_21_digits_is_not_silently_truncated():
    result = parse_invoice_text("р/с 407028100000000000012")
    assert result.bank_account == ""


def test_conflicting_account_clears_field():
    result = parse_invoice_text("р/с 40702810000000000001\nр/с 40702810000000000002")
    assert result.bank_account == ""
    assert any("Неоднозначное" in warning for warning in result.warnings)


def test_duplicate_identical_totals_not_false_conflict():
    result = parse_invoice_text("Total: 100,00\nИтого: 100.00")
    assert result.amount_rub == "100.00"


def test_invoice_header_and_date_label_disagree():
    result = parse_invoice_text("Счёт № 81 от 28.10.2026\nДата: 29.10.2026")
    assert result.invoice_number == "81"
    assert result.issued_on == ""
    assert any("Неоднозначное" in w and "дата" in w for w in result.warnings)


def test_invalid_date_does_not_become_valid():
    result = parse_invoice_text("Счёт № A-1 от 32.10.2026\nИтого: 100")
    assert result.issued_on == ""


def test_unlabeled_vat_does_not_become_total():
    result = parse_invoice_text("НДС: 12.00\nЦена: 100.00")
    assert result.amount_rub == ""


def test_cannot_read_next_line_as_bank_account():
    result = parse_invoice_text("Bank Account:\nDate: 2026-10-29\n40702810000000000001")
    assert result.bank_account == ""


def test_extracted_invoice_values_are_not_html():
    result = parse_invoice_text("Invoice No: VALID-17\nTotal: 123.00\n<script>alert(1)</script>")
    assert result.invoice_number == "VALID-17"
    assert all("<script>" not in value for value in (result.invoice_number, result.bank_account))


def test_too_much_text_rejected():
    with pytest.raises(PdfRejected):
        parse_invoice_text("A" * 30_001)


def test_pdf_preview_with_valid_text_does_not_write_to_database(client):
    pdf_data = BytesIO()
    doc = canvas.Canvas(pdf_data)
    for offset, line in enumerate((
        "Invoice No: EN-55", "Total Due: 1,234,567.89",
        "Bank Account: DE89 3704 0044 0532 0130 00", "Date: 29/10/2026",
    )):
        doc.drawString(40, 700 - offset * 24, line)
    doc.save()

    with Session(client.test_engine) as db:
        before = db.scalar(select(func.count()).select_from(Invoice))
    response = client.post(
        "/pdf-import", files={"file": ("sample.pdf", pdf_data.getvalue(), "application/pdf")},
        data={"csrf_token": client.csrf_token},
    )
    assert response.status_code == 200
    assert "EN-55" in response.text
    assert "1234567.89" in response.text
    assert "DE89370400440532013000" in response.text
    with Session(client.test_engine) as db:
        assert db.scalar(select(func.count()).select_from(Invoice)) == before


def test_extract_draft_rejects_non_pdf_still():
    with pytest.raises(PdfRejected):
        extract_draft(b"not a pdf")
