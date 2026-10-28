from io import BytesIO

from pypdf import PdfWriter

from app.services.pdf_import import PdfRejected, extract_draft


def pdf_bytes(text=None):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_reject_non_pdf():
    try:
        extract_draft(b"something else")
        assert False
    except PdfRejected:
        pass


def test_reject_oversize():
    try:
        extract_draft(b"%PDF-" + b"x" * (2 * 1024 * 1024))
        assert False
    except PdfRejected:
        pass


def test_pdf_without_text_rejected():
    try:
        extract_draft(pdf_bytes())
        assert False
    except PdfRejected:
        pass


def test_requires_login_for_pdf(client):
    client.cookies.clear()
    assert client.get("/pdf-import", follow_redirects=False).status_code == 401


def test_upload_requires_csrf(client):
    response = client.post("/pdf-import", files={"file": ("invoice.pdf", pdf_bytes(), "application/pdf")}, data={"csrf_token": "incorrect"})
    assert response.status_code == 403


def test_pdf_upload_rejects_fake_mime(client):
    response = client.post("/pdf-import", files={"file": ("invoice.pdf", b"hello", "text/plain")}, data={"csrf_token": client.csrf_token})
    assert response.status_code == 415


def test_pdf_preview_does_not_save_invoice(client):
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from app.models import Invoice
    with Session(client.test_engine) as db:
        count_before = db.scalar(select(func.count()).select_from(Invoice))
    response = client.post("/pdf-import", files={"file": ("invoice.pdf", pdf_bytes(), "application/pdf")}, data={"csrf_token": client.csrf_token})
    assert response.status_code == 422
    with Session(client.test_engine) as db:
        assert db.scalar(select(func.count()).select_from(Invoice)) == count_before


def test_pdf_extracts_labeled_fields():
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.setFont("Helvetica", 12)
    for index, line in enumerate(("Invoice No: TEST-2026-404", "Total: 175000.50", "Bank Account: DE89370400440532013000", "Date: 2026-10-28")):
        pdf.drawString(35, 700 - 24 * index, line)
    pdf.save()
    draft = extract_draft(buf.getvalue())
    assert draft.invoice_number == "TEST-2026-404"
    assert draft.amount_rub == "175000.50"
    assert draft.bank_account == "DE89370400440532013000"
    assert draft.issued_on == "2026-10-28"
