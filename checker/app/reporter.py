"""Publish a ProbeResult back to the coordinator via the results Redis Stream."""
import json
from datetime import UTC, datetime

import redis.asyncio as aioredis
import structlog

from app.config import settings
from app.probe import ProbeResult

log = structlog.get_logger(__name__)


def _build_idempotency_key(service_id: str, node_id: str, scheduled_round: int) -> str:
    """
    Deterministic key: same service + node + scheduling round always maps
    to the same key so retrying the same task never double-writes.
    """
    return f"{service_id}:{node_id}:{scheduled_round}"


async def report_result(
    redis: aioredis.Redis,
    service_id: str,
    scheduled_round: int,
    result: ProbeResult,
) -> None:
    idem_key = _build_idempotency_key(service_id, settings.NODE_ID, scheduled_round)
    checked_at = datetime.now(UTC).isoformat()

    raw_headers_str = json.dumps(result.raw_headers) if result.raw_headers else "None"

    payload = {
        "service_id": service_id,
        "checker_node_id": settings.NODE_ID,
        "checked_at": checked_at,
        "status": result.status,
        "status_code": str(result.status_code) if result.status_code is not None else "None",
        "response_ms": str(result.response_ms) if result.response_ms is not None else "None",
        "error_message": result.error_message or "None",
        "raw_headers": raw_headers_str,
        "idempotency_key": idem_key,
    }

    entry_id = await redis.xadd(
        settings.RESULTS_STREAM, payload, maxlen=100_000, approximate=True
    )
    log.debug("result_reported", service_id=service_id, status=result.status, entry_id=entry_id)
