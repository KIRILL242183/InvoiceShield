"""Add v0.3 tables and backfill old high/medium risk invoices. Safe to rerun."""
from sqlalchemy import select

from app import models  # noqa: F401  register tables
from app.database import Base, SessionLocal, engine
from app.models import Incident, IncidentEvent, Invoice


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        old = list(db.scalars(
            select(Invoice.id).outerjoin(Incident, Incident.invoice_id == Invoice.id)
            .where(Invoice.risk_level.in_(("MEDIUM", "HIGH")), Incident.id.is_(None))
            .order_by(Invoice.id)
        ))
        for invoice_id in old:
            incident = Incident(invoice_id=invoice_id)
            db.add(incident)
            db.flush()
            db.add(IncidentEvent(
                incident_id=incident.id, event_type="IMPORTED",
                details="Инцидент создан для ранее проверенного счёта",
            ))
        db.commit()
        print(f"Готово: создано {len(old)} инцидентов для существующих счетов.")
        print("Поставщики, счета и пользователи не изменялись.")


if __name__ == "__main__":
    main()
