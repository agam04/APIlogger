"""
HTTP probe with retry/backoff.

Returns a ProbeResult that maps cleanly to the CheckResult schema.
Handles: timeouts, connection errors, TLS errors, unexpected status codes.
"""
import asyncio
import time
from dataclasses import dataclass

import httpx
import structlog

from app.config import settings

log = structlog.get_logger(__name__)


@dataclass
class ProbeResult:
    status: str          # up | down | timeout | error
    status_code: int | None
    response_ms: int | None
    error_message: str | None
    raw_headers: dict | None


async def probe(
    url: str,
    method: str,
    timeout_ms: int,
    expected_status: int,
    headers: dict,
    body: str | None,
) -> ProbeResult:
    """Run the probe with up to MAX_PROBE_RETRIES retries on transient errors."""
    last_result: ProbeResult | None = None
    for attempt in range(settings.MAX_PROBE_RETRIES + 1):
        if attempt > 0:
            delay_ms = settings.RETRY_BACKOFF_BASE_MS * (2 ** (attempt - 1))
            await asyncio.sleep(delay_ms / 1000)

        last_result = await _do_probe(url, method, timeout_ms, expected_status, headers, body)

        # Only retry on network-level errors, not on HTTP status mismatches
        if last_result.status != "error":
            break

    return last_result  # type: ignore[return-value]


async def _do_probe(
    url: str,
    method: str,
    timeout_ms: int,
    expected_status: int,
    headers: dict,
    body: str | None,
) -> ProbeResult:
    timeout = httpx.Timeout(timeout_ms / 1000)
    start = time.monotonic()

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            verify=True,
        ) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body.encode() if body else None,
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        ok = response.status_code == expected_status

        return ProbeResult(
            status="up" if ok else "down",
            status_code=response.status_code,
            response_ms=elapsed_ms,
            error_message=None if ok else f"Expected {expected_status}, got {response.status_code}",
            raw_headers=dict(response.headers),
        )

    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ProbeResult(
            status="timeout",
            status_code=None,
            response_ms=elapsed_ms,
            error_message=f"Timeout after {elapsed_ms}ms: {type(exc).__name__}",
            raw_headers=None,
        )
    except httpx.ConnectError as exc:
        return ProbeResult(
            status="error",
            status_code=None,
            response_ms=None,
            error_message=f"Connection error: {exc}",
            raw_headers=None,
        )
    except Exception as exc:
        return ProbeResult(
            status="error",
            status_code=None,
            response_ms=None,
            error_message=f"{type(exc).__name__}: {exc}",
            raw_headers=None,
        )
