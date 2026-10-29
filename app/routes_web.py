"""Server-rendered authenticated dashboard and HTML forms."""
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.auth import Identity, ensure_admin, lookup_identity, require_web_user, verify_csrf
from app.database import get_db
from app.schemas import InvoiceCreate, SupplierCreate
from app.services.incidents import list_incidents
from app.services.invoices import (
    SupplierAlreadyExists, SupplierNotFound, list_audit, list_invoices,
    list_suppliers, register_invoice, register_supplier,
)

from app.ui import make_templates

router = APIRouter(include_in_schema=False)
templates = make_templates()
NOTICES = {
    "supplier_added": "Поставщик добавлен.",
    "invoice_added": "Счёт проверен и сохранён.",
    "supplier_exists": "Поставщик с таким именем уже существует.",
    "supplier_missing": "Сначала добавьте поставщика.",
    "invalid_input": "Проверьте введённые данные: обязательные поля, сумму и реквизиты.",
}


def go_home(notice: str) -> RedirectResponse:
    return RedirectResponse(url="/?" + urlencode({"notice": notice}), status_code=303)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, notice: str = "", db: Session = Depends(get_db)):
    identity = lookup_identity(request, db)
    if identity is None:
        return RedirectResponse(url="/login", status_code=303)
    suppliers = list_suppliers(db)
    invoices = list_invoices(db)
    incidents = list_incidents(db, limit=6)
    is_admin = identity.user.role == "admin"
    audit = list_audit(db, limit=15) if is_admin else []
    stats = {
        "suppliers": len(suppliers), "invoices": len(invoices),
        "high": sum(i.risk_level == "HIGH" for i in invoices),
        "medium": sum(i.risk_level == "MEDIUM" for i in invoices),
    }
    return templates.TemplateResponse(
        request=request, name="index.html",
        context={
            "suppliers": suppliers, "invoices": invoices, "audit": audit,
            "incidents": incidents,
            "stats": stats, "today": date.today().isoformat(),
            "notice": NOTICES.get(notice),
            "notice_is_error": notice not in ("supplier_added", "invoice_added"),
            "csrf_token": identity.session.csrf_token,
            "username": identity.user.username,
            "is_admin": is_admin,
        },
    )


@router.post("/web/suppliers")
def create_supplier(
    name: str = Form(""), bank_account: str = Form(""), csrf_token: str = Form(""),
    identity: Identity = Depends(require_web_user), db: Session = Depends(get_db),
):
    verify_csrf(identity, csrf_token)
    ensure_admin(identity)
    try:
        payload = SupplierCreate(name=name, bank_account=bank_account)
        register_supplier(db, payload, actor_id=identity.user.id)
    except ValidationError:
        return go_home("invalid_input")
    except SupplierAlreadyExists:
        return go_home("supplier_exists")
    return go_home("supplier_added")


@router.post("/web/invoices")
def create_invoice(
    supplier_id: str = Form(""), invoice_number: str = Form(""),
    amount_rub: str = Form(""), bank_account: str = Form(""),
    issued_on: str = Form(""), csrf_token: str = Form(""),
    identity: Identity = Depends(require_web_user), db: Session = Depends(get_db),
):
    verify_csrf(identity, csrf_token)
    try:
        payload = InvoiceCreate(
            supplier_id=supplier_id, invoice_number=invoice_number,
            amount_rub=Decimal(amount_rub), bank_account=bank_account,
            issued_on=issued_on,
        )
        register_invoice(db, payload, actor_id=identity.user.id)
    except (ValidationError, InvalidOperation, ValueError):
        return go_home("invalid_input")
    except SupplierNotFound:
        return go_home("supplier_missing")
    return go_home("invoice_added")
