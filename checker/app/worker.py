"""
Checker worker main loop.

Pull CheckTask messages from the tasks Redis Stream (consumer group),
probe the target endpoint, and publish the result to the results stream.

Fault tolerance:
  - If this process dies mid-task, the un-ACKed message stays in the PEL
    (pending entry list) and another consumer can claim it via XAUTOCLAIM
    after a timeout. The coordinator's idempotency_key prevents double-writes.
  - Semaphore limits concurrent probes to settings.CONCURRENCY.
"""
import asyncio
import json
import signal

import redis.asyncio as aioredis
import structlog

from app.config import settings
from app.probe import probe
from app.reporter import report_result

log = structlog.get_logger(__name__)

_shutdown = asyncio.Event()
_semaphore: asyncio.Semaphore | None = None


def _handle_signal(sig: int, frame) -> None:
    log.info("shutdown_signal_received", signal=sig)
    _shutdown.set()


async def run() -> None:
    global _semaphore
    _semaphore = asyncio.Semaphore(settings.CONCURRENCY)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    # Create consumer group if needed (idempotent)
    try:
        await redis.xgroup_create(settings.TASKS_STREAM, settings.TASKS_GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    log.info("checker_worker_started", node_id=settings.NODE_ID, concurrency=settings.CONCURRENCY)

    # First, reclaim any pending tasks from a previous crashed instance of this node
    await _reclaim_pending(redis)

    tasks: set[asyncio.Task] = set()

    while not _shutdown.is_set():
        try:
            messages = await redis.xreadgroup(
                groupname=settings.TASKS_GROUP,
                consumername=settings.NODE_ID,
                streams={settings.TASKS_STREAM: ">"},
                count=settings.CONCURRENCY,
                block=settings.BLOCK_MS,
            )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("xreadgroup_error", exc=str(exc))
            await asyncio.sleep(1)
            continue

        if not messages:
            continue

        for _stream, entries in messages:
            for entry_id, data in entries:
                t = asyncio.create_task(_handle_task(redis, entry_id, data))
                tasks.add(t)
                t.add_done_callback(tasks.discard)

    # Graceful shutdown: wait for in-flight tasks
    if tasks:
        log.info("waiting_for_in_flight_tasks", count=len(tasks))
        await asyncio.gather(*tasks, return_exceptions=True)

    await redis.aclose()
    log.info("checker_worker_stopped")


async def _handle_task(redis: aioredis.Redis, entry_id: str, raw: dict) -> None:
    async with _semaphore:
        try:
            task = _parse_task(raw)
        except Exception as exc:
            log.warning("task_parse_error", entry_id=entry_id, exc=str(exc))
            await redis.xack(settings.TASKS_STREAM, settings.TASKS_GROUP, entry_id)
            return

        log.debug("probing", service_id=task["service_id"], url=task["url"])
        result = await probe(
            url=task["url"],
            method=task["method"],
            timeout_ms=task["timeout_ms"],
            expected_status=task["expected_status"],
            headers=task["headers"],
            body=task.get("body"),
        )

        await report_result(redis, task["service_id"], task["scheduled_round"], result)
        await redis.xack(settings.TASKS_STREAM, settings.TASKS_GROUP, entry_id)

        log.info(
            "check_done",
            service_id=task["service_id"],
            status=result.status,
            response_ms=result.response_ms,
        )


async def _reclaim_pending(redis: aioredis.Redis) -> None:
    """Claim messages that were pending for > 60 s (previous crashed instance)."""
    try:
        result = await redis.xautoclaim(
            settings.TASKS_STREAM,
            settings.TASKS_GROUP,
            settings.NODE_ID,
            min_idle_time=60_000,  # 60 s
            start_id="0-0",
            count=100,
        )
        reclaimed = result[1] if result else []
        if reclaimed:
            log.info("reclaimed_pending_tasks", count=len(reclaimed))
    except Exception as exc:
        log.warning("reclaim_failed", exc=str(exc))


def _parse_task(raw: dict) -> dict:
    return {
        "service_id": raw["service_id"],
        "url": raw["url"],
        "method": raw["method"],
        "timeout_ms": int(raw["timeout_ms"]),
        "expected_status": int(raw["expected_status"]),
        "headers": json.loads(raw["headers"]) if raw.get("headers") else {},
        "body": raw.get("body") if raw.get("body") != "None" else None,
        "interval_secs": int(raw["interval_secs"]),
        "scheduled_round": int(raw["scheduled_round"]),
    }


if __name__ == "__main__":
    asyncio.run(run())
