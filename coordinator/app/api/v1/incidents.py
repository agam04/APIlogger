"""Incident list, detail, and AI summary trigger."""
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.db.models import Incident, Service

router = APIRouter(prefix="/incidents", tags=["incidents"])


class AIStructured(BaseModel):
    root_cause: str
    confidence: float
    risk_level: str
    recommended_actions: list[str]
    estimated_impact: str
    similar_past_incident: str | None


class IncidentResponse(BaseModel):
    id: str
    service_id: str
    service_name: str
    started_at: str
    resolved_at: str | None
    trigger_reason: str
    ai_summary: str | None
    ai_structured: AIStructured | None
    ai_generated_at: str | None
    alert_sent: bool

    model_config = {"from_attributes": True}


class PaginatedIncidents(BaseModel):
    items: list[IncidentResponse]
    total: int
    page: int
    page_size: int


def _inc_to_response(inc: Incident) -> IncidentResponse:
    structured = None
    if inc.ai_structured:
        try:
            structured = AIStructured(**inc.ai_structured)
        except Exception:
            pass

    return IncidentResponse(
        id=str(inc.id),
        service_id=str(inc.service_id),
        service_name=inc.service.name if inc.service else "",
        started_at=inc.started_at.isoformat(),
        resolved_at=inc.resolved_at.isoformat() if inc.resolved_at else None,
        trigger_reason=inc.trigger_reason,
        ai_summary=inc.ai_summary,
        ai_structured=structured,
        ai_generated_at=inc.ai_generated_at.isoformat() if inc.ai_generated_at else None,
        alert_sent=inc.alert_sent,
    )


@router.get("", response_model=PaginatedIncidents)
async def list_incidents(
    db: DBSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    open_only: bool = False,
) -> PaginatedIncidents:
    # Join to services to enforce user ownership
    svc_ids_q = select(Service.id).where(Service.user_id == user.id)

    q = (
        select(Incident)
        .options(selectinload(Incident.service))
        .where(Incident.service_id.in_(svc_ids_q))
    )
    if open_only:
        q = q.where(Incident.resolved_at.is_(None))

    total_r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_r.scalar_one()

    results_r = await db.execute(
        q.order_by(Incident.started_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = results_r.scalars().all()
    return PaginatedIncidents(
        items=[_inc_to_response(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: uuid.UUID, db: DBSession, user: CurrentUser) -> IncidentResponse:
    svc_ids_q = select(Service.id).where(Service.user_id == user.id)
    result = await db.execute(
        select(Incident)
        .options(selectinload(Incident.service))
        .where(Incident.id == incident_id, Incident.service_id.in_(svc_ids_q))
    )
    inc = result.scalar_one_or_none()
    if inc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return _inc_to_response(inc)


@router.post("/{incident_id}/generate-summary", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ai_summary(
    incident_id: uuid.UUID,
    db: DBSession,
    user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict:
    """Manually re-trigger the AI summary for an incident."""
    from app.incidents.ai_summary import generate_and_store_summary

    svc_ids_q = select(Service.id).where(Service.user_id == user.id)
    result = await db.execute(
        select(Incident).where(
            Incident.id == incident_id, Incident.service_id.in_(svc_ids_q)
        )
    )
    inc = result.scalar_one_or_none()
    if inc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")

    background_tasks.add_task(generate_and_store_summary, str(incident_id))
    return {"status": "queued", "incident_id": str(incident_id)}
