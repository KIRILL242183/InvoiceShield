"""Use-cases shared by the HTML interface and REST API."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditEvent, Incident, IncidentEvent, Invoice, SecurityEvent, Supplier
from app.schemas import InvoiceCreate, SupplierCreate
from app.services.risk import evaluate


def _lock_supplier_for_invoice(db: Session, supplier_id: int) -> Supplier | None:
    """Serialize checks for the same supplier to avoid duplicate-detection races.

    PostgreSQL supports row-level FOR UPDATE locks. SQLite cannot lock a row,
    so BEGIN IMMEDIATE reserves the single-writer lock before reading invoices.
    This is deliberately simple and suitable for our educational application.
    """
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        # Must be executed before the first SELECT inside this transaction.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return db.get(Supplier, supplier_id)
    return db.scalar(
        select(Supplier).where(Supplier.id == supplier_id).with_for_update()
    )


class SupplierAlreadyExists(Exception):
    pass


class SupplierNotFound(Exception):
    pass


def register_supplier(db: Session, payload: SupplierCreate, actor_id: int | None = None) -> Supplier:
    supplier = Supplier(name=payload.name, bank_account=payload.bank_account)
    db.add(supplier)
    try:
        db.flush()
        db.add(AuditEvent(
            action="SUPPLIER_CREATED", entity_type="supplier", entity_id=supplier.id,
            details="Поставщик добавлен в реестр",
        ))
        if actor_id is not None:
            db.add(SecurityEvent(user_id=actor_id, event="SUPPLIER_CREATED", detail="Поставщик добавлен"))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SupplierAlreadyExists from exc
    db.refresh(supplier)
    return supplier


def register_invoice(db: Session, payload: InvoiceCreate, actor_id: int | None = None) -> Invoice:
    supplier = _lock_supplier_for_invoice(db, payload.supplier_id)
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
    if result.level in ("MEDIUM", "HIGH"):
        incident = Incident(invoice_id=invoice.id)
        db.add(incident)
        db.flush()
        db.add(IncidentEvent(
            incident_id=incident.id, actor_id=actor_id, event_type="CREATED",
            details="Инцидент открыт автоматически после проверки счёта",
        ))
    db.add(AuditEvent(
        action="INVOICE_CHECKED", entity_type="invoice", entity_id=invoice.id,
        details=f"Анализ завершён; уровень риска: {result.level}; баллы: {result.score}",
    ))
    if actor_id is not None:
        db.add(SecurityEvent(user_id=actor_id, event="INVOICE_CHECKED", detail=f"score={result.score}"))
    db.commit()
    db.refresh(invoice)
    return invoice


def list_suppliers(db: Session) -> list[Supplier]:
    return list(db.scalars(select(Supplier).order_by(Supplier.name)).all())


def list_invoices(db: Session, limit: int = 100) -> list[Invoice]:
    return list(db.scalars(select(Invoice).order_by(Invoice.id.desc()).limit(limit)).all())


def list_audit(db: Session, limit: int = 100) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)).all())
