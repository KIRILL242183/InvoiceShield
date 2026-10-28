"""Investigation endpoints for authenticated analysts and administrators."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import Identity, ensure_admin, require_api_csrf, require_api_user
from app.database import get_db
from app.schemas import (
    IncidentAssign, IncidentCommentCreate, IncidentDetailOut, IncidentEventOut,
    IncidentOut, IncidentStatusChange,
)
from app.services.incidents import (
    IncidentConflict, IncidentNotFound, InvalidAssignee, InvalidTransition,
    add_comment, assign_incident, change_status, get_incident, list_events,
    list_incidents, to_public, to_public_event,
)

router = APIRouter(prefix="/api/incidents", tags=["Investigations"])


def handle_error(exc: Exception):
    if isinstance(exc, IncidentNotFound):
        raise HTTPException(404, "Инцидент не найден") from exc
    if isinstance(exc, IncidentConflict):
        raise HTTPException(409, "Инцидент изменён другим пользователем; обновите страницу") from exc
    if isinstance(exc, InvalidTransition):
        raise HTTPException(409, "Недопустимый переход статуса") from exc
    if isinstance(exc, InvalidAssignee):
        raise HTTPException(422, "Исполнитель не найден или заблокирован") from exc
    raise exc


@router.get("", response_model=list[IncidentOut])
def get_all(status: str | None = Query(default=None, pattern="^(OPEN|IN_REVIEW|RESOLVED|FALSE_POSITIVE)$"),
            limit: int = Query(default=100, ge=1, le=100),
            db: Session = Depends(get_db), identity: Identity = Depends(require_api_user)):
    return [to_public(c) for c in list_incidents(db, status=status, limit=limit)]


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_one(incident_id: int, db: Session = Depends(get_db),
            identity: Identity = Depends(require_api_user)):
    try:
        case = get_incident(db, incident_id)
    except IncidentNotFound as exc:
        handle_error(exc)
    return {"incident": to_public(case),
            "events": [to_public_event(e) for e in list_events(db, incident_id)]}


@router.post("/{incident_id}/status", response_model=IncidentOut)
def post_status(incident_id: int, payload: IncidentStatusChange,
                db: Session = Depends(get_db), identity: Identity = Depends(require_api_csrf)):
    try:
        return to_public(change_status(db, incident_id, payload.status,
                                       payload.version, identity.user.id))
    except (IncidentNotFound, IncidentConflict, InvalidTransition) as exc:
        handle_error(exc)


@router.post("/{incident_id}/assign", response_model=IncidentOut)
def post_assign(incident_id: int, payload: IncidentAssign,
                db: Session = Depends(get_db), identity: Identity = Depends(require_api_csrf)):
    ensure_admin(identity)
    try:
        return to_public(assign_incident(db, incident_id, payload.assignee_id,
                                         payload.version, identity.user.id))
    except (IncidentNotFound, IncidentConflict, InvalidAssignee) as exc:
        handle_error(exc)


@router.post("/{incident_id}/comments", response_model=IncidentEventOut, status_code=201)
def post_comment(incident_id: int, payload: IncidentCommentCreate,
                 db: Session = Depends(get_db), identity: Identity = Depends(require_api_csrf)):
    try:
        event = add_comment(db, incident_id, payload.comment, identity.user.id)
    except IncidentNotFound as exc:
        handle_error(exc)
    return to_public_event(event)
