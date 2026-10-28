"""Populate ONLY a local/demo database with synthetic suppliers and invoices."""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Supplier
from app.schemas import InvoiceCreate, SupplierCreate
from app.services.invoices import register_invoice, register_supplier


def add_invoice(db, supplier_id, number, amount, account):
    register_invoice(db, InvoiceCreate(
        supplier_id=supplier_id, invoice_number=number, amount_rub=Decimal(amount),
        bank_account=account, issued_on=date(2026, 10, 28),
    ))


def main():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.scalar(select(Supplier.id).limit(1)) is not None:
            print("База уже содержит поставщиков. Демо-данные не добавлены.")
            return
        a = register_supplier(db, SupplierCreate(
            name="ООО Альфа Логистик", bank_account="RU-ALFA-440022",
        ))
        b = register_supplier(db, SupplierCreate(
            name="ООО Север Тех", bank_account="RU-SEVER-778899",
        ))
        c = register_supplier(db, SupplierCreate(
            name="ООО Вектор Снабжение", bank_account="RU-VEKTOR-553311",
        ))
        add_invoice(db, a.id, "ALF-001", "145000.00", "RU-ALFA-440022")
        add_invoice(db, b.id, "ST-2026-01", "329000.00", "RU-SEVER-778899")
        add_invoice(db, a.id, "ALF-002", "85000.00", "RU-UNFAMILIAR-999")
        add_invoice(db, c.id, "VEC-550", "1590000.00", "RU-VEKTOR-553311")
        add_invoice(db, b.id, "ST-2026-01", "329000.00", "RU-SEVER-778899")
        add_invoice(db, c.id, "VEC-551", "293000.00", "RU-VEKTOR-553311")
        print("Добавлены 3 синтетических поставщика и 6 счетов.")


if __name__ == "__main__":
    main()
