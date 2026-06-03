"""Internal health + metrics endpoints."""

import time
from dataclasses import dataclass, field

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DBSession, RedisConn
from app.core.config import settings

router = APIRouter(tags=["observability"])


# Simple in-process counters (replace with prometheus_client in production)
@dataclass
class _Metrics:
    checks_ingested: int = 0
    incidents_opened: int = 0
    incidents_resolved: int = 0
    ai_summaries_generated: int = 0
    alerts_sent: int = 0
    start_time: float = field(default_factory=time.time)


metrics = _Metrics()


@router.get("/healthz")
async def healthz(db: DBSession, redis: RedisConn) -> dict:
    """Liveness + dependency probe."""
    errors: list[str] = []

    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        errors.append(f"db: {exc}")

    try:
        await redis.ping()
    except Exception as exc:
        errors.append(f"redis: {exc}")

    return {
        "status": "ok" if not errors else "degraded",
        "service": settings.SERVICE_NAME,
        "env": settings.ENV,
        "errors": errors,
    }


@router.get("/metrics")
async def get_metrics() -> dict:
    """Exposes internal counters. Mount a Prometheus exporter in production."""
    uptime = time.time() - metrics.start_time
    return {
        "uptime_seconds": round(uptime, 1),
        "checks_ingested": metrics.checks_ingested,
        "incidents_opened": metrics.incidents_opened,
        "incidents_resolved": metrics.incidents_resolved,
        "ai_summaries_generated": metrics.ai_summaries_generated,
        "alerts_sent": metrics.alerts_sent,
    }
