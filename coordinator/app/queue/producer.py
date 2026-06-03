"""Publish check-task messages to the Redis Stream consumed by checker nodes."""
import json
from dataclasses import asdict, dataclass

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class CheckTask:
    service_id: str
    url: str
    method: str
    timeout_ms: int
    expected_status: int
    headers: dict
    body: str | None
    interval_secs: int
    # round number used as part of the idempotency key on the checker side
    scheduled_round: int


async def publish_check_task(redis: aioredis.Redis, task: CheckTask) -> str:
    """XADD to the tasks stream. Returns the Redis stream entry ID."""
    payload = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in asdict(task).items()}
    entry_id = await redis.xadd(settings.TASKS_STREAM, payload, maxlen=50_000, approximate=True)
    log.debug("published_check_task", service_id=task.service_id, entry_id=entry_id)
    return entry_id


async def ensure_consumer_groups(redis: aioredis.Redis) -> None:
    """Idempotently create consumer groups on startup."""
    for stream, group in [
        (settings.TASKS_STREAM, settings.TASKS_GROUP),
        (settings.RESULTS_STREAM, settings.RESULTS_GROUP),
    ]:
        try:
            await redis.xgroup_create(stream, group, id="0", mkstream=True)
            log.info("created_consumer_group", stream=stream, group=group)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                pass  # group already exists
            else:
                raise
