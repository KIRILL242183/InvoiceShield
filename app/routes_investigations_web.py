"""Server-rendered incident queue and detail forms (no client-side JS required)."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import Identity, ensure_admin, lookup_identity, require_web_user, verify_csrf
from app.database import get_db
from app.models import User
from app.services.incidents import (
    IncidentConflict, IncidentNotFound, InvalidAssignee, InvalidTransition,
    TRANSITIONS, add_comment, assign_incident, change_status, get_incident,
    list_events, list_incidents,
)

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")
MESSAGES = {
    "status": "Статус изменён.", "assigned": "Ответственный назначен.",
    "comment": "Комментарий добавлен.",
    "stale": "Данные изменились в другой вкладке. Обновите информацию и попробуйте ещё раз.",
    "transition": "Этот переход статуса недопустим.",
    "invalid": "Проверьте введённые данные.",
}


def redirect_to(incident_id: int, notice: str):
    return RedirectResponse("/incidents/" + str(incident_id) + "?" + urlencode({"notice": notice}),
                            status_code=303)


@router.get("/incidents", response_class=HTMLResponse)
def queue(request: Request, status: str = "", db: Session = Depends(get_db)):
    identity = lookup_identity(request, db)
    if identity is None:
        return RedirectResponse("/login", status_code=303)
    if status not in ("", "OPEN", "IN_REVIEW", "RESOLVED", "FALSE_POSITIVE"):
        raise HTTPException(422, "Неизвестный фильтр")
    cases = list_incidents(db, status=status or None)
    return templates.TemplateResponse(request=request, name="incidents.html", context={
        "cases": cases, "status_filter": status, "username": identity.user.username,
        "csrf_token": identity.session.csrf_token,
    })


@router.get("/incidents/{incident_id}", response_class=HTMLResponse)
def detail(request: Request, incident_id: int, notice: str = "", db: Session = Depends(get_db)):
    identity = lookup_identity(request, db)
    if identity is None:
        return RedirectResponse("/login", status_code=303)
    try:
        case = get_incident(db, incident_id)
    except IncidentNotFound as exc:
        raise HTTPException(404, "Инцидент не найден") from exc
    users = list(db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))) \
        if identity.user.role == "admin" else []
    return templates.TemplateResponse(request=request, name="incident_detail.html", context={
        "case": case, "events": list_events(db, incident_id), "users": users,
        "transitions": sorted(TRANSITIONS[case.status]), "notice": MESSAGES.get(notice),
        "username": identity.user.username, "is_admin": identity.user.role == "admin",
        "csrf_token": identity.session.csrf_token,
    })


@router.post("/web/incidents/{incident_id}/status")
def web_status(incident_id: int, status: str = Form(""), version: int = Form(0),
               csrf_token: str = Form(""),
               identity: Identity = Depends(require_web_user), db: Session = Depends(get_db)):
    verify_csrf(identity, csrf_token)
    try:
        change_status(db, incident_id, status, version, identity.user.id)
    except IncidentNotFound as exc:
        raise HTTPException(404, "Инцидент не найден") from exc
    except IncidentConflict:
        return redirect_to(incident_id, "stale")
    except InvalidTransition:
        return redirect_to(incident_id, "transition")
    return redirect_to(incident_id, "status")


@router.post("/web/incidents/{incident_id}/assign")
def web_assign(incident_id: int, assignee_id: str = Form(""), version: int = Form(0),
               csrf_token: str = Form(""),
               identity: Identity = Depends(require_web_user), db: Session = Depends(get_db)):
    verify_csrf(identity, csrf_token)
    ensure_admin(identity)
    try:
        target = int(assignee_id) if assignee_id else None
        assign_incident(db, incident_id, target, version, identity.user.id)
    except (ValueError, InvalidAssignee):
        return redirect_to(incident_id, "invalid")
    except IncidentNotFound as exc:
        raise HTTPException(404, "Инцидент не найден") from exc
    except IncidentConflict:
        return redirect_to(incident_id, "stale")
    return redirect_to(incident_id, "assigned")


@router.post("/web/incidents/{incident_id}/comments")
def web_comment(incident_id: int, comment: str = Form(""), csrf_token: str = Form(""),
                identity: Identity = Depends(require_web_user), db: Session = Depends(get_db)):
    verify_csrf(identity, csrf_token)
    try:
        add_comment(db, incident_id, comment, identity.user.id)
    except ValueError:
        return redirect_to(incident_id, "invalid")
    except IncidentNotFound as exc:
        raise HTTPException(404, "Инцидент не найден") from exc
    return redirect_to(incident_id, "comment")
