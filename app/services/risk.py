"""Explainable heuristic fraud signals: NOT a probability of fraud."""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Invoice, Supplier
from app.schemas import InvoiceCreate

HIGH_VALUE_KOPECKS = 100_000_000  # > 1,000,000.00 RUB


@dataclass(frozen=True)
class RiskResult:
    score: int
    level: str
    findings: list[dict]


def evaluate(db: Session, supplier: Supplier, data: InvoiceCreate) -> RiskResult:
    findings: list[dict] = []

    if data.bank_account != supplier.bank_account:
        findings.append({
            "code": "BANK_ACCOUNT_CHANGED",
            "points": 70,
            "message": "Реквизиты счёта не совпадают с реестром поставщика; подтвердите их независимо.",
        })

    previous = db.scalar(
        select(Invoice.id).where(
            Invoice.supplier_id == supplier.id,
            func.lower(Invoice.invoice_number) == data.invoice_number.lower(),
        ).limit(1)
    )
    if previous is not None:
        findings.append({
            "code": "DUPLICATE_NUMBER",
            "points": 60,
            "message": "У этого поставщика уже зарегистрирован счёт с таким номером.",
        })

    kopecks = int(data.amount_rub * 100)
    if kopecks > HIGH_VALUE_KOPECKS:
        findings.append({
            "code": "LARGE_AMOUNT",
            "points": 35,
            "message": "Сумма превышает демонстрационный порог 1 000 000 ₽.",
        })

    score = min(100, sum(item["points"] for item in findings))
    level = "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW"
    return RiskResult(score=score, level=level, findings=findings)
