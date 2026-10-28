"""Investigation workflow, optimistic concurrency and append-only timeline."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.models import Incident, IncidentEvent, Invoice, User

TRANSITIONS = {
    "OPEN": {"IN_REVIEW"},
    "IN_REVIEW": {"RESOLVED", "FALSE_POSITIVE"},
    "RESOLVED": {"IN_REVIEW"},
    "FALSE_POSITIVE": {"IN_REVIEW"},
}
STATUSES = {"OPEN", "IN_REVIEW", "RESOLVED", "FALSE_POSITIVE"}


class IncidentNotFound(Exception):
    pass


class IncidentConflict(Exception):
    pass


class InvalidTransition(Exception):
    pass


class InvalidAssignee(Exception):
    pass


def _now():
    return datetime.now(timezone.utc)


def get_incident(db: Session, incident_id: int) -> Incident:
    incident = db.scalar(
        select(Incident)
        .options(joinedload(Incident.invoice).joinedload(Invoice.supplier),
                 joinedload(Incident.assignee))
        .where(Incident.id == incident_id)
    )
    if incident is None:
        raise IncidentNotFound
    return incident


def list_incidents(db: Session, *, status: str | None = None, limit: int = 100) -> list[Incident]:
    stmt = (
        select(Incident)
        .options(joinedload(Incident.invoice).joinedload(Invoice.supplier),
                 joinedload(Incident.assignee))
        .order_by(Incident.id.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Incident.status == status)
    return list(db.scalars(stmt).all())


def list_events(db: Session, incident_id: int) -> list[IncidentEvent]:
    return list(db.scalars(
        select(IncidentEvent).options(joinedload(IncidentEvent.actor))
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.id.asc())
    ).all())


def to_public(incident: Incident) -> dict:
    return {
        "id": incident.id, "invoice_id": incident.invoice_id,
        "invoice_number": incident.invoice.invoice_number,
        "supplier_name": incident.invoice.supplier.name,
        "risk_score": incident.invoice.risk_score,
        "risk_level": incident.invoice.risk_level,
        "status": incident.status,
        "assignee_username": incident.assignee.username if incident.assignee else None,
        "version": incident.version, "created_at": incident.created_at,
        "updated_at": incident.updated_at,
    }


def to_public_event(event: IncidentEvent) -> dict:
    return {
        "id": event.id, "event_type": event.event_type,
        "actor_username": event.actor.username if event.actor else None,
        "details": event.details, "comment": event.comment,
        "created_at": event.created_at,
    }


def _update(db: Session, incident_id: int, expected_version: int, **changes) -> Incident:
    """Atomic compare-and-swap prevents silent lost updates from two browser tabs."""
    stmt = (
        update(Incident)
        .where(Incident.id == incident_id, Incident.version == expected_version)
        .values(version=Incident.version + 1, updated_at=_now(), **changes)
    )
    if db.execute(stmt).rowcount != 1:
        db.rollback()
        raise IncidentConflict
    db.flush()
    db.expire_all()
    return get_incident(db, incident_id)


def change_status(db: Session, incident_id: int, new_status: str,
                  expected_version: int, actor_id: int) -> Incident:
    incident = get_incident(db, incident_id)
    if incident.version != expected_version:
        raise IncidentConflict
    if new_status not in TRANSITIONS[incident.status]:
        raise InvalidTransition
    previous = incident.status
    updated = _update(db, incident_id, expected_version, status=new_status)
    db.add(IncidentEvent(
        incident_id=incident_id, actor_id=actor_id, event_type="STATUS_CHANGED",
        details=f"{previous} → {new_status}",
    ))
    db.commit()
    return updated


def assign_incident(db: Session, incident_id: int, assignee_id: int | None,
                    expected_version: int, actor_id: int) -> Incident:
    incident = get_incident(db, incident_id)
    if incident.version != expected_version:
        raise IncidentConflict
    assignee = db.get(User, assignee_id) if assignee_id is not None else None
    if assignee_id is not None and (assignee is None or not assignee.is_active):
        raise InvalidAssignee
    updated = _update(db, incident_id, expected_version, assignee_id=assignee_id)
    db.add(IncidentEvent(
        incident_id=incident_id, actor_id=actor_id, event_type="ASSIGNED",
        details=f"Исполнитель: {assignee.username if assignee else 'не назначен'}",
    ))
    db.commit()
    return updated


def add_comment(db: Session, incident_id: int, comment: str, actor_id: int) -> IncidentEvent:
    text = comment.strip()
    if not (1 <= len(text) <= 1000):
        raise ValueError("Комментарий должен содержать от 1 до 1000 символов")
    get_incident(db, incident_id)
    event = IncidentEvent(
        incident_id=incident_id, actor_id=actor_id, event_type="COMMENTED",
        details="Добавлен комментарий", comment=text,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
