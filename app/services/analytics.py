"""Read-only financial risk reports. Values always reflect stored invoices, not live payments."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import StringIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Incident, Invoice, Supplier

MAX_REPORT_ROWS = 5000
LEVELS = ("LOW", "MEDIUM", "HIGH")
STATUSES = ("OPEN", "IN_REVIEW", "RESOLVED", "FALSE_POSITIVE")


@dataclass(frozen=True)
class ReportFilter:
    from_date: date | None = None
    to_date: date | None = None
    supplier_id: int | None = None
    risk_level: str | None = None


class ReportTooLarge(ValueError):
    """The report exceeds the explicit export/analysis row limit."""


def collect_report(db: Session, filters: ReportFilter) -> dict:
    """Compute metrics for the selected *invoice issue dates* (not creation dates).

    The demo limit makes oversized exports explicit rather than silently truncating
    data. This is not suitable as an OLAP backend for large production datasets.
    """
    conditions = []
    if filters.from_date is not None:
        conditions.append(Invoice.issued_on >= filters.from_date)
    if filters.to_date is not None:
        conditions.append(Invoice.issued_on <= filters.to_date)
    if filters.supplier_id is not None:
        conditions.append(Invoice.supplier_id == filters.supplier_id)
    if filters.risk_level is not None:
        conditions.append(Invoice.risk_level == filters.risk_level)

    total = db.scalar(select(func.count()).select_from(Invoice).where(*conditions)) or 0
    if total > MAX_REPORT_ROWS:
        raise ReportTooLarge(f"Найдено {total} счетов; сузьте фильтры до {MAX_REPORT_ROWS} строк")

    stmt = (select(Invoice, Supplier.name, Incident.status)
            .join(Supplier, Supplier.id == Invoice.supplier_id)
            .outerjoin(Incident, Incident.invoice_id == Invoice.id)
            .where(*conditions)
            .order_by(Invoice.issued_on.desc(), Invoice.id.desc()))
    rows = db.execute(stmt).all()

    levels = Counter({level: 0 for level in LEVELS})
    statuses = Counter({status: 0 for status in STATUSES})
    suppliers: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount_kopecks": 0, "high": 0})
    amount_kopecks = 0
    risky_amount_kopecks = 0
    for invoice, supplier_name, incident_status in rows:
        levels[invoice.risk_level] += 1
        amount_kopecks += invoice.amount_kopecks
        if invoice.risk_level in ("HIGH", "MEDIUM"):
            risky_amount_kopecks += invoice.amount_kopecks
        bucket = suppliers[supplier_name]
        bucket["count"] += 1
        bucket["amount_kopecks"] += invoice.amount_kopecks
        if invoice.risk_level == "HIGH":
            bucket["high"] += 1
        if incident_status:
            statuses[incident_status] += 1

    breakdown = [{"name": name, **values} for name, values in suppliers.items()]
    breakdown.sort(key=lambda item: (-item["high"], -item["count"], item["name"]))
    return {
        "total": total,
        "amount_kopecks": amount_kopecks,
        "risky_amount_kopecks": risky_amount_kopecks,
        "levels": levels,
        "statuses": statuses,
        "suppliers": breakdown,
        "rows": rows,
    }


def rubles(kopecks: int) -> str:
    return str((Decimal(kopecks) / 100).quantize(Decimal("0.01")))


def safe_cell(value: str) -> str:
    """Prevent spreadsheet applications from evaluating CSV cells as formulas."""
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def report_csv(report: dict) -> bytes:
    out = StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["Invoice ID", "Invoice number", "Supplier", "Issued on", "Amount RUB",
                     "Risk score", "Risk level", "Incident status"])
    for invoice, supplier_name, status in report["rows"]:
        writer.writerow([invoice.id, safe_cell(invoice.invoice_number), safe_cell(supplier_name),
                         invoice.issued_on.isoformat(), rubles(invoice.amount_kopecks),
                         invoice.risk_score, invoice.risk_level, status or ""])
    return ("\ufeff" + out.getvalue()).encode("utf-8")
