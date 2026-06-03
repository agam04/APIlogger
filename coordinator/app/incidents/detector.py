"""
Quorum-based incident detector.

Algorithm:
  - After each CheckResult is persisted, we look at all results for this
    service in the last QUORUM_WINDOW_SECS seconds.
  - If the fraction of results that are 'down'/'timeout'/'error' ≥
    QUORUM_FRACTION, we open an incident (if none is open).
  - If an incident is open and the fraction drops below QUORUM_FRACTION,
    we close it.

By counting across checker nodes instead of trusting a single node, we
eliminate false alerts from individual node network blips.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy import func

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import CheckResult, Incident, Service, ServiceStatus

log = get_logger(__name__)

# One lock per service so concurrent invocations don't race on incidents
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(service_id: str) -> asyncio.Lock:
    if service_id not in _locks:
        _locks[service_id] = asyncio.Lock()
    return _locks[service_id]


async def process_check_result(result: dict) -> None:
    service_id = result["service_id"]
    async with _get_lock(service_id):
        await _evaluate(service_id)


async def _evaluate(service_id: str) -> None:
    sid = uuid.UUID(service_id)
    window_start = datetime.now(UTC) - timedelta(seconds=settings.QUORUM_WINDOW_SECS)

    async with AsyncSessionLocal() as db:
        # Count total and failing results in the quorum window
        total_r = await db.execute(
            select(func.count(CheckResult.id)).where(
                CheckResult.service_id == sid,
                CheckResult.checked_at >= window_start,
            )
        )
        total = total_r.scalar_one()
        if total == 0:
            return

        failing_r = await db.execute(
            select(func.count(CheckResult.id)).where(
                CheckResult.service_id == sid,
                CheckResult.checked_at >= window_start,
                CheckResult.status.in_(["down", "timeout", "error"]),
            )
        )
        failing = failing_r.scalar_one()
        failure_fraction = failing / total

        is_quorum_down = failure_fraction >= settings.QUORUM_FRACTION

        # Fetch open incident
        open_inc_r = await db.execute(
            select(Incident).where(
                Incident.service_id == sid,
                Incident.resolved_at.is_(None),
            )
        )
        open_incident = open_inc_r.scalar_one_or_none()

        if is_quorum_down and open_incident is None:
            await _open_incident(db, sid, failure_fraction, failing, total)
        elif not is_quorum_down and open_incident is not None:
            await _resolve_incident(db, open_incident)

        # Always update service_status
        await _update_status(db, sid, is_quorum_down)
        await db.commit()


async def _open_incident(db, service_id: uuid.UUID, fraction: float, failing: int, total: int) -> None:
    reason = f"Quorum failure: {failing}/{total} checks failed ({fraction:.0%}) in last {settings.QUORUM_WINDOW_SECS}s"
    incident = Incident(service_id=service_id, trigger_reason=reason)
    db.add(incident)
    await db.flush()

    log.warning("incident_opened", service_id=str(service_id), reason=reason)

    from app.api.v1.health import metrics
    metrics.incidents_opened += 1

    # AI summary + alerting are triggered asynchronously
    asyncio.create_task(_post_open_tasks(str(incident.id), str(service_id)))


async def _resolve_incident(db, incident: Incident) -> None:
    incident.resolved_at = datetime.now(UTC)
    await db.flush()

    log.info("incident_resolved", incident_id=str(incident.id), service_id=str(incident.service_id))

    from app.api.v1.health import metrics
    metrics.incidents_resolved += 1

    asyncio.create_task(_post_resolve_tasks(str(incident.id), str(incident.service_id)))


async def _update_status(db, service_id: uuid.UUID, is_down: bool) -> None:
    result = await db.execute(select(ServiceStatus).where(ServiceStatus.service_id == service_id))
    status_row = result.scalar_one_or_none()
    new_status = "down" if is_down else "up"

    if status_row is None:
        status_row = ServiceStatus(service_id=service_id)
        db.add(status_row)

    if status_row.current_status != new_status:
        status_row.since = datetime.now(UTC)
    status_row.current_status = new_status
    status_row.last_checked_at = datetime.now(UTC)

    # Publish SSE event for live dashboard
    await _publish_status_event(str(service_id), new_status)


async def _publish_status_event(service_id: str, new_status: str) -> None:
    try:
        from app.api.deps import get_redis_pool
        import json
        redis = get_redis_pool()
        event = json.dumps({"type": "status_change", "service_id": service_id, "status": new_status})
        await redis.publish(settings.EVENTS_CHANNEL, event)
    except Exception as exc:
        log.debug("sse_publish_failed", exc=str(exc))


async def _post_open_tasks(incident_id: str, service_id: str) -> None:
    from app.incidents.ai_summary import generate_and_store_summary
    from app.incidents.alerting import send_incident_alert

    await generate_and_store_summary(incident_id)
    await send_incident_alert(incident_id, event="opened")


async def _post_resolve_tasks(incident_id: str, service_id: str) -> None:
    from app.incidents.alerting import send_incident_alert

    await send_incident_alert(incident_id, event="resolved")
