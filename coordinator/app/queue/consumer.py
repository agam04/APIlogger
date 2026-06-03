"""
Coordinator-side result consumer.

Reads CheckResult messages from the Redis results stream, writes them
to Postgres (idempotent via unique constraint on idempotency_key), then
feeds the incident detector.
"""
import asyncio
import json
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.db.models import CheckResult
from app.incidents.detector import process_check_result

log = get_logger(__name__)

CONSUMER_NAME = "coordinator-0"
BATCH_SIZE = 50
BLOCK_MS = 2_000  # block 2 s waiting for messages


async def run_result_consumer(redis: aioredis.Redis) -> None:
    """Long-running task: drain the results stream and persist each result."""
    log.info("result_consumer_started", stream=settings.RESULTS_STREAM)

    while True:
        try:
            messages = await redis.xreadgroup(
                groupname=settings.RESULTS_GROUP,
                consumername=CONSUMER_NAME,
                streams={settings.RESULTS_STREAM: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )
            if not messages:
                continue

            for _stream, entries in messages:
                for entry_id, data in entries:
                    await _handle_result(redis, entry_id, data)

        except asyncio.CancelledError:
            log.info("result_consumer_stopping")
            return
        except Exception as exc:
            log.error("result_consumer_error", exc=str(exc))
            await asyncio.sleep(1)


async def _handle_result(redis: aioredis.Redis, entry_id: str, raw: dict) -> None:
    try:
        result = _parse_result(raw)
    except Exception as exc:
        log.warning("result_parse_error", entry_id=entry_id, exc=str(exc))
        await redis.xack(settings.RESULTS_STREAM, settings.RESULTS_GROUP, entry_id)
        return

    async with AsyncSessionLocal() as db:
        row = CheckResult(
            service_id=result["service_id"],
            checker_node_id=result["checker_node_id"],
            checked_at=result["checked_at"],
            status=result["status"],
            status_code=result.get("status_code"),
            response_ms=result.get("response_ms"),
            error_message=result.get("error_message"),
            raw_headers=result.get("raw_headers"),
            idempotency_key=result["idempotency_key"],
        )
        db.add(row)
        try:
            await db.commit()
            log.debug(
                "result_persisted",
                service_id=result["service_id"],
                status=result["status"],
                node=result["checker_node_id"],
            )
        except IntegrityError:
            # Duplicate — checker retried; safe to ignore
            await db.rollback()
            log.debug("result_duplicate_skipped", idempotency_key=result["idempotency_key"])
            await redis.xack(settings.RESULTS_STREAM, settings.RESULTS_GROUP, entry_id)
            return
        except Exception as exc:
            await db.rollback()
            log.error("result_persist_error", exc=str(exc))
            # Don't ACK — will be re-delivered
            return

    # Feed detector (outside DB session to avoid long-held connections)
    try:
        await process_check_result(result)
    except Exception as exc:
        log.error("detector_error", exc=str(exc))

    # Increment internal metric
    from app.api.v1.health import metrics
    metrics.checks_ingested += 1

    await redis.xack(settings.RESULTS_STREAM, settings.RESULTS_GROUP, entry_id)


def _parse_result(raw: dict) -> dict:
    status_code = raw.get("status_code")
    response_ms = raw.get("response_ms")
    raw_headers_str = raw.get("raw_headers")

    return {
        "service_id": raw["service_id"],
        "checker_node_id": raw["checker_node_id"],
        "checked_at": datetime.fromisoformat(raw["checked_at"]),
        "status": raw["status"],
        "status_code": int(status_code) if status_code and status_code != "None" else None,
        "response_ms": int(response_ms) if response_ms and response_ms != "None" else None,
        "error_message": raw.get("error_message") or None,
        "raw_headers": json.loads(raw_headers_str) if raw_headers_str and raw_headers_str != "None" else None,
        "idempotency_key": raw["idempotency_key"],
    }
