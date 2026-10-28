"""Use-cases shared by the HTML interface and REST API."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditEvent, Invoice, Supplier
from app.schemas import InvoiceCreate, SupplierCreate
from app.services.risk import evaluate


class SupplierAlreadyExists(Exception):
    pass


class SupplierNotFound(Exception):
    pass


def register_supplier(db: Session, payload: SupplierCreate) -> Supplier:
    supplier = Supplier(name=payload.name, bank_account=payload.bank_account)
    db.add(supplier)
    try:
        db.flush()
        db.add(AuditEvent(
            action="SUPPLIER_CREATED", entity_type="supplier", entity_id=supplier.id,
            details="Поставщик добавлен в реестр",
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SupplierAlreadyExists from exc
    db.refresh(supplier)
    return supplier


def register_invoice(db: Session, payload: InvoiceCreate) -> Invoice:
    supplier = db.get(Supplier, payload.supplier_id)
    if supplier is None:
        raise SupplierNotFound
    result = evaluate(db, supplier, payload)
    invoice = Invoice(
        supplier_id=payload.supplier_id,
        invoice_number=payload.invoice_number,
        amount_kopecks=int(payload.amount_rub * 100),
        bank_account=payload.bank_account,
        issued_on=payload.issued_on,
        risk_score=result.score,
        risk_level=result.level,
        findings=result.findings,
    )
    db.add(invoice)
    db.flush()
    db.add(AuditEvent(
        action="INVOICE_CHECKED", entity_type="invoice", entity_id=invoice.id,
        details=f"Анализ завершён; уровень риска: {result.level}; баллы: {result.score}",
    ))
    db.commit()
    db.refresh(invoice)
    return invoice


def list_suppliers(db: Session) -> list[Supplier]:
    return list(db.scalars(select(Supplier).order_by(Supplier.name)).all())


def list_invoices(db: Session, limit: int = 100) -> list[Invoice]:
    return list(db.scalars(select(Invoice).order_by(Invoice.id.desc()).limit(limit)).all())


def list_audit(db: Session, limit: int = 100) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)).all())
