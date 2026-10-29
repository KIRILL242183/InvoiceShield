"""Authenticated risk analytics. Only administrators can export detailed CSV."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, ensure_admin, lookup_identity, require_api_user
from app.database import get_db
from app.models import Supplier
from app.services.analytics import (LEVELS, ReportFilter, ReportTooLarge,
                                    collect_report, report_csv, rubles)

router = APIRouter(tags=["Analytics"])
templates = Jinja2Templates(directory="app/templates")


def _filters(from_date: date | None, to_date: date | None,
             supplier_id: int | None, risk_level: str | None) -> ReportFilter:
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="Начальная дата позже конечной")
    if supplier_id is not None and supplier_id < 1:
        raise HTTPException(status_code=422, detail="Неверный поставщик")
    if risk_level is not None and risk_level not in LEVELS:
        raise HTTPException(status_code=422, detail="Неизвестный уровень риска")
    return ReportFilter(from_date, to_date, supplier_id, risk_level)


def _report(db: Session, filters: ReportFilter) -> dict:
    try:
        return collect_report(db, filters)
    except ReportTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.get("/analytics", response_class=HTMLResponse, include_in_schema=False)
def analytics_page(request: Request, from_date: date | None = None, to_date: date | None = None,
                   supplier_id: int | None = None, risk_level: str | None = None,
                   db: Session = Depends(get_db)):
    identity = lookup_identity(request, db)
    if identity is None:
        return RedirectResponse("/login", status_code=303)
    filters = _filters(from_date, to_date, supplier_id, risk_level)
    report = _report(db, filters)
    suppliers = list(db.scalars(select(Supplier).order_by(Supplier.name)))
    for item in report["suppliers"]:
        item["amount_rub"] = rubles(item["amount_kopecks"])
    return templates.TemplateResponse(request=request, name="analytics.html", context={
        "report": report, "suppliers": suppliers, "filters": filters,
        "total_rub": rubles(report["amount_kopecks"]),
        "risky_rub": rubles(report["risky_amount_kopecks"]),
        "username": identity.user.username, "is_admin": identity.user.role == "admin",
        "csrf_token": identity.session.csrf_token,
    })


@router.get("/api/analytics/summary")
def analytics_summary(from_date: date | None = None, to_date: date | None = None,
                      supplier_id: int | None = Query(default=None, ge=1),
                      risk_level: str | None = None,
                      identity: Identity = Depends(require_api_user),
                      db: Session = Depends(get_db)):
    filters = _filters(from_date, to_date, supplier_id, risk_level)
    report = _report(db, filters)
    return {
        "count": report["total"],
        "amount_rub": rubles(report["amount_kopecks"]),
        "risky_amount_rub": rubles(report["risky_amount_kopecks"]),
        "risk_levels": dict(report["levels"]),
        "incident_statuses": dict(report["statuses"]),
    }


@router.get("/api/analytics/export.csv")
def analytics_export(from_date: date | None = None, to_date: date | None = None,
                     supplier_id: int | None = Query(default=None, ge=1),
                     risk_level: str | None = None,
                     identity: Identity = Depends(require_api_user),
                     db: Session = Depends(get_db)):
    ensure_admin(identity)
    report = _report(db, _filters(from_date, to_date, supplier_id, risk_level))
    return Response(
        content=report_csv(report), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="invoiceshield-report.csv"',
                 "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
