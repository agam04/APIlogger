"""
APScheduler-based check scheduler.

For each active service, we create a dedicated IntervalTrigger job that
publishes a CheckTask to the Redis Stream.  Jobs are re-synced from the DB
every minute so newly added / deleted services are picked up without restart.
"""

import math
import random
import time

import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import Service
from app.queue.producer import CheckTask, publish_check_task

log = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None
_redis: aioredis.Redis | None = None


def get_scheduler() -> AsyncIOScheduler:
    if _scheduler is None:
        raise RuntimeError("Scheduler not initialised")
    return _scheduler


def _job_id(service_id: str) -> str:
    return f"check:{service_id}"


def _make_round(service_id: str, interval_secs: int) -> int:
    """Deterministic round counter — buckets time into interval-sized windows."""
    return math.floor(time.time() / interval_secs)


async def _enqueue_check(
    service_id: str,
    url: str,
    method: str,
    timeout_ms: int,
    expected_status: int,
    headers: dict,
    body: str | None,
    interval_secs: int,
) -> None:
    if _redis is None:
        return
    round_num = _make_round(service_id, interval_secs)
    task = CheckTask(
        service_id=service_id,
        url=url,
        method=method,
        timeout_ms=timeout_ms,
        expected_status=expected_status,
        headers=headers,
        body=body,
        interval_secs=interval_secs,
        scheduled_round=round_num,
    )
    try:
        await publish_check_task(_redis, task)
    except Exception as exc:
        log.error("enqueue_check_failed", service_id=service_id, exc=str(exc))


async def _sync_jobs() -> None:
    """Pull active services from DB and ensure each has a scheduled job."""
    scheduler = get_scheduler()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Service).where(Service.is_active == True))  # noqa: E712
        services = result.scalars().all()

    active_ids = {str(s.id) for s in services}
    existing_ids = {job.id.removeprefix("check:") for job in scheduler.get_jobs() if job.id.startswith("check:")}

    # Remove stale jobs
    for stale_id in existing_ids - active_ids:
        scheduler.remove_job(_job_id(stale_id))
        log.info("removed_stale_job", service_id=stale_id)

    # Add / update jobs
    for svc in services:
        sid = str(svc.id)
        jitter = random.randint(0, settings.SCHEDULER_JITTER_SECS)
        kwargs = dict(
            service_id=sid,
            url=svc.url,
            method=svc.method,
            timeout_ms=svc.timeout_ms,
            expected_status=svc.expected_status,
            headers=svc.headers,
            body=svc.body,
            interval_secs=svc.interval_secs,
        )
        if sid in existing_ids:
            job = scheduler.get_job(_job_id(sid))
            if job:
                # Reschedule if interval changed
                current_interval = job.trigger.interval.total_seconds()
                if int(current_interval) != svc.interval_secs:
                    scheduler.reschedule_job(
                        _job_id(sid),
                        trigger=IntervalTrigger(seconds=svc.interval_secs, jitter=jitter),
                    )
                    log.info("rescheduled_job", service_id=sid, interval=svc.interval_secs)
        else:
            scheduler.add_job(
                _enqueue_check,
                trigger=IntervalTrigger(seconds=svc.interval_secs, jitter=jitter),
                id=_job_id(sid),
                kwargs=kwargs,
                replace_existing=True,
                coalesce=True,
                max_instances=1,
            )
            log.info("scheduled_job", service_id=sid, interval=svc.interval_secs)


async def start_scheduler(redis: aioredis.Redis) -> AsyncIOScheduler:
    global _scheduler, _redis
    _redis = redis

    _scheduler = AsyncIOScheduler(timezone="UTC")
    # Sync jobs every 60 seconds
    _scheduler.add_job(_sync_jobs, trigger=IntervalTrigger(seconds=60), id="sync_jobs", replace_existing=True)
    _scheduler.start()

    # Do an immediate sync so services are scheduled without waiting 60 s
    await _sync_jobs()
    log.info("scheduler_started")
    return _scheduler


async def stop_scheduler() -> None:
    if _scheduler:
        _scheduler.shutdown(wait=False)
        log.info("scheduler_stopped")
