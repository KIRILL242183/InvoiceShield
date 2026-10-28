"""Authenticated REST API: the admin manages suppliers and reads audit logs."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth import Identity, ensure_admin, require_api_csrf, require_api_user
from app.database import get_db
from app.models import Invoice
from app.schemas import AuditOut, InvoiceCreate, InvoiceOut, SupplierCreate, SupplierOut
from app.services.invoices import (
    SupplierAlreadyExists, SupplierNotFound, list_audit, list_invoices,
    list_suppliers, register_invoice, register_supplier,
)

router = APIRouter(prefix="/api", tags=["API"])


@router.get("/suppliers", response_model=list[SupplierOut])
def get_suppliers(db: Session = Depends(get_db), identity: Identity = Depends(require_api_user)):
    return list_suppliers(db)


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def post_supplier(payload: SupplierCreate, db: Session = Depends(get_db),
                  identity: Identity = Depends(require_api_csrf)):
    ensure_admin(identity)
    try:
        return register_supplier(db, payload, actor_id=identity.user.id)
    except SupplierAlreadyExists as exc:
        raise HTTPException(status_code=409, detail="Поставщик с таким именем уже существует") from exc


@router.get("/invoices", response_model=list[InvoiceOut])
def get_invoices(limit: int = Query(default=100, ge=1, le=100),
                 db: Session = Depends(get_db), identity: Identity = Depends(require_api_user)):
    return list_invoices(db, limit)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db),
                identity: Identity = Depends(require_api_user)):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Счёт не найден")
    return invoice


@router.post("/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def post_invoice(payload: InvoiceCreate, db: Session = Depends(get_db),
                 identity: Identity = Depends(require_api_csrf)):
    try:
        return register_invoice(db, payload, actor_id=identity.user.id)
    except SupplierNotFound as exc:
        raise HTTPException(status_code=404, detail="Поставщик не найден") from exc


@router.get("/audit", response_model=list[AuditOut])
def get_audit(limit: int = Query(default=100, ge=1, le=100),
              db: Session = Depends(get_db), identity: Identity = Depends(require_api_user)):
    ensure_admin(identity)
    return list_audit(db, limit)
