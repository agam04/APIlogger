"""Read-only endpoints for check result history with pagination."""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.db.models import CheckResult, Service

router = APIRouter(prefix="/services/{service_id}/checks", tags=["checks"])


class CheckResultResponse(BaseModel):
    id: str
    checker_node_id: str
    checked_at: str
    status: str
    status_code: int | None
    response_ms: int | None
    error_message: str | None

    model_config = {"from_attributes": True}


class PaginatedChecks(BaseModel):
    items: list[CheckResultResponse]
    total: int
    page: int
    page_size: int


class LatencyStats(BaseModel):
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    uptime_pct: float | None
    total_checks: int


async def _assert_service_owned(db: DBSession, service_id: uuid.UUID, user_id: uuid.UUID) -> None:
    result = await db.execute(
        select(Service.id).where(Service.id == service_id, Service.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")


@router.get("", response_model=PaginatedChecks)
async def list_checks(
    service_id: uuid.UUID,
    db: DBSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
    since: datetime | None = None,
    until: datetime | None = None,
    node_id: str | None = None,
) -> PaginatedChecks:
    await _assert_service_owned(db, service_id, user.id)

    q = select(CheckResult).where(CheckResult.service_id == service_id)
    if since:
        q = q.where(CheckResult.checked_at >= since)
    if until:
        q = q.where(CheckResult.checked_at <= until)
    if node_id:
        q = q.where(CheckResult.checker_node_id == node_id)

    total_r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_r.scalar_one()

    results_r = await db.execute(
        q.order_by(CheckResult.checked_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = results_r.scalars().all()

    return PaginatedChecks(
        items=[
            CheckResultResponse(
                id=str(r.id),
                checker_node_id=r.checker_node_id,
                checked_at=r.checked_at.isoformat(),
                status=r.status,
                status_code=r.status_code,
                response_ms=r.response_ms,
                error_message=r.error_message,
            )
            for r in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=LatencyStats)
async def get_stats(
    service_id: uuid.UUID,
    db: DBSession,
    user: CurrentUser,
    since: datetime | None = None,
    until: datetime | None = None,
) -> LatencyStats:
    await _assert_service_owned(db, service_id, user.id)

    q = select(CheckResult).where(
        CheckResult.service_id == service_id,
        CheckResult.response_ms.is_not(None),
    )
    if since:
        q = q.where(CheckResult.checked_at >= since)
    if until:
        q = q.where(CheckResult.checked_at <= until)

    # Use PostgreSQL percentile_cont for accurate server-side percentiles
    subq = q.subquery()
    stats_r = await db.execute(
        select(
            func.percentile_cont(0.50).within_group(subq.c.response_ms).label("p50"),
            func.percentile_cont(0.95).within_group(subq.c.response_ms).label("p95"),
            func.percentile_cont(0.99).within_group(subq.c.response_ms).label("p99"),
            func.count(subq.c.id).label("total"),
        )
    )
    row = stats_r.one()

    # uptime = fraction of checks with status 'up'
    total_q = await db.execute(
        select(func.count(CheckResult.id)).where(CheckResult.service_id == service_id)
    )
    up_q = await db.execute(
        select(func.count(CheckResult.id)).where(
            CheckResult.service_id == service_id, CheckResult.status == "up"
        )
    )
    total_all = total_q.scalar_one()
    total_up = up_q.scalar_one()

    return LatencyStats(
        p50_ms=float(row.p50) if row.p50 is not None else None,
        p95_ms=float(row.p95) if row.p95 is not None else None,
        p99_ms=float(row.p99) if row.p99 is not None else None,
        uptime_pct=round(total_up / total_all * 100, 2) if total_all else None,
        total_checks=total_all,
    )
