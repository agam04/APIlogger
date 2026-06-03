"""Service CRUD + alert-rule management."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, HttpUrl, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DBSession
from app.db.models import AlertRule, Service, ServiceStatus

router = APIRouter(prefix="/services", tags=["services"])


# ---- Schemas ----


class ServiceCreate(BaseModel):
    name: str
    url: HttpUrl
    method: str = "GET"
    interval_secs: int = 60
    timeout_ms: int = 5000
    expected_status: int = 200
    headers: dict[str, str] = {}
    body: str | None = None

    @field_validator("method")
    @classmethod
    def method_upper(cls, v: str) -> str:
        v = v.upper()
        if v not in {"GET", "POST", "PUT", "PATCH", "HEAD"}:
            raise ValueError("method must be GET/POST/PUT/PATCH/HEAD")
        return v

    @field_validator("interval_secs")
    @classmethod
    def min_interval(cls, v: int) -> int:
        if v < 10:
            raise ValueError("interval_secs must be ≥ 10")
        return v


class ServiceUpdate(BaseModel):
    name: str | None = None
    url: HttpUrl | None = None
    method: str | None = None
    interval_secs: int | None = None
    timeout_ms: int | None = None
    expected_status: int | None = None
    headers: dict[str, str] | None = None
    body: str | None = None
    is_active: bool | None = None


class StatusResponse(BaseModel):
    current_status: str
    since: str | None
    uptime_7d: float | None
    p50_ms: int | None
    p99_ms: int | None


class ServiceResponse(BaseModel):
    id: str
    name: str
    url: str
    method: str
    interval_secs: int
    timeout_ms: int
    expected_status: int
    headers: dict
    body: str | None
    is_active: bool
    created_at: str
    status: StatusResponse | None

    model_config = {"from_attributes": True}


class PaginatedServices(BaseModel):
    items: list[ServiceResponse]
    total: int
    page: int
    page_size: int


class AlertRuleCreate(BaseModel):
    channel: str
    destination: str
    on_incident: bool = True
    on_resolve: bool = True

    @field_validator("channel")
    @classmethod
    def valid_channel(cls, v: str) -> str:
        if v not in {"email", "slack", "discord"}:
            raise ValueError("channel must be email/slack/discord")
        return v


class AlertRuleResponse(BaseModel):
    id: str
    channel: str
    destination: str
    on_incident: bool
    on_resolve: bool

    model_config = {"from_attributes": True}


# ---- Helpers ----


def _to_service_response(svc: Service) -> ServiceResponse:
    st = svc.status
    return ServiceResponse(
        id=str(svc.id),
        name=svc.name,
        url=str(svc.url),
        method=svc.method,
        interval_secs=svc.interval_secs,
        timeout_ms=svc.timeout_ms,
        expected_status=svc.expected_status,
        headers=svc.headers,
        body=svc.body,
        is_active=svc.is_active,
        created_at=svc.created_at.isoformat(),
        status=StatusResponse(
            current_status=st.current_status,
            since=st.since.isoformat() if st else None,
            uptime_7d=float(st.uptime_7d) if st and st.uptime_7d is not None else None,
            p50_ms=st.p50_ms if st else None,
            p99_ms=st.p99_ms if st else None,
        )
        if st
        else None,
    )


async def _get_service_or_404(db: DBSession, service_id: uuid.UUID, user_id: uuid.UUID) -> Service:
    result = await db.execute(
        select(Service)
        .options(selectinload(Service.status))
        .where(Service.id == service_id, Service.user_id == user_id)
    )
    svc = result.scalar_one_or_none()
    if svc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return svc


# ---- Routes ----


@router.get("", response_model=PaginatedServices)
async def list_services(
    db: DBSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedServices:
    offset = (page - 1) * page_size
    total_q = await db.execute(select(func.count()).select_from(Service).where(Service.user_id == user.id))
    total = total_q.scalar_one()

    result = await db.execute(
        select(Service)
        .options(selectinload(Service.status))
        .where(Service.user_id == user.id)
        .order_by(Service.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    services = result.scalars().all()
    return PaginatedServices(
        items=[_to_service_response(s) for s in services],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(body: ServiceCreate, db: DBSession, user: CurrentUser) -> ServiceResponse:
    svc = Service(
        user_id=user.id,
        name=body.name,
        url=str(body.url),
        method=body.method,
        interval_secs=body.interval_secs,
        timeout_ms=body.timeout_ms,
        expected_status=body.expected_status,
        headers=body.headers,
        body=body.body,
    )
    db.add(svc)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Service name already exists") from None
    # Initialise status row
    svc_status = ServiceStatus(service_id=svc.id, current_status="unknown")
    db.add(svc_status)
    await db.flush()
    await db.refresh(svc, ["status"])
    return _to_service_response(svc)


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(service_id: uuid.UUID, db: DBSession, user: CurrentUser) -> ServiceResponse:
    svc = await _get_service_or_404(db, service_id, user.id)
    return _to_service_response(svc)


@router.patch("/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: uuid.UUID, body: ServiceUpdate, db: DBSession, user: CurrentUser
) -> ServiceResponse:
    svc = await _get_service_or_404(db, service_id, user.id)
    for field, value in body.model_dump(exclude_none=True).items():
        if field == "url":
            value = str(value)
        setattr(svc, field, value)
    await db.flush()
    return _to_service_response(svc)


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    svc = await _get_service_or_404(db, service_id, user.id)
    await db.delete(svc)
    await db.flush()


# ---- Alert rules ----


@router.get("/{service_id}/alert-rules", response_model=list[AlertRuleResponse])
async def list_alert_rules(service_id: uuid.UUID, db: DBSession, user: CurrentUser) -> list[AlertRule]:
    await _get_service_or_404(db, service_id, user.id)
    result = await db.execute(select(AlertRule).where(AlertRule.service_id == service_id))
    return list(result.scalars().all())


@router.post(
    "/{service_id}/alert-rules",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_alert_rule(
    service_id: uuid.UUID, body: AlertRuleCreate, db: DBSession, user: CurrentUser
) -> AlertRule:
    await _get_service_or_404(db, service_id, user.id)
    rule = AlertRule(
        service_id=service_id,
        channel=body.channel,
        destination=body.destination,
        on_incident=body.on_incident,
        on_resolve=body.on_resolve,
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Alert rule already exists") from None
    return rule


@router.delete("/{service_id}/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(service_id: uuid.UUID, rule_id: uuid.UUID, db: DBSession, user: CurrentUser) -> None:
    await _get_service_or_404(db, service_id, user.id)
    result = await db.execute(select(AlertRule).where(AlertRule.id == rule_id, AlertRule.service_id == service_id))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")
    await db.delete(rule)
