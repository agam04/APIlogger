"""
Node-death recovery test.

Simulates a checker node dying mid-batch by:
1. Writing check tasks to the Redis stream
2. Claiming them as a consumer (simulating a node that got the tasks)
3. NOT acknowledging them (simulating a crash)
4. Running a second node's reclaim logic (XAUTOCLAIM)
5. Asserting the tasks are recovered and processed

This is an integration test that requires Redis to be running.
"""
import asyncio
import json
import os
import pytest
import pytest_asyncio
from datetime import UTC, datetime

import redis.asyncio as aioredis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
TEST_STREAM = "apilogger:node-death-test"
TEST_GROUP = "test-checkers"


@pytest_asyncio.fixture
async def redis_client():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield r
    await r.delete(TEST_STREAM)
    await r.aclose()


@pytest.mark.asyncio
async def test_node_death_recovery(redis_client: aioredis.Redis):
    """
    A task claimed by dead-node-1 but not ACKed should be reclaimed
    by alive-node-2 via XAUTOCLAIM after idle timeout.
    """
    # Create consumer group
    try:
        await redis_client.xgroup_create(TEST_STREAM, TEST_GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    # Publish a task
    task_payload = {
        "service_id": "test-svc-1",
        "url": "https://httpbin.org/get",
        "method": "GET",
        "timeout_ms": "5000",
        "expected_status": "200",
        "headers": "{}",
        "body": "None",
        "interval_secs": "60",
        "scheduled_round": "1",
    }
    await redis_client.xadd(TEST_STREAM, task_payload)

    # Dead node claims the task (reads but doesn't ACK — simulates crash)
    dead_node_messages = await redis_client.xreadgroup(
        groupname=TEST_GROUP,
        consumername="dead-node-1",
        streams={TEST_STREAM: ">"},
        count=10,
        block=1000,
    )
    assert dead_node_messages, "Should have received the task"

    # Verify the task is in dead-node-1's pending list
    pending = await redis_client.xpending_range(
        TEST_STREAM, TEST_GROUP, min="-", max="+", count=10
    )
    assert len(pending) == 1
    assert pending[0]["consumer"] == "dead-node-1"

    # Force the message to appear idle (override min_idle_time to 0 for testing)
    entry_id = pending[0]["message_id"]

    # Alive node reclaims via XAUTOCLAIM with min_idle=0ms (instant for test)
    result = await redis_client.xautoclaim(
        TEST_STREAM,
        TEST_GROUP,
        "alive-node-2",
        min_idle_time=0,  # claim immediately for test purposes
        start_id="0-0",
        count=10,
    )

    reclaimed = result[1] if result else []
    assert len(reclaimed) == 1, f"Should have reclaimed 1 task, got {len(reclaimed)}"

    # Confirm the message is now owned by alive-node-2
    pending2 = await redis_client.xpending_range(
        TEST_STREAM, TEST_GROUP, min="-", max="+", count=10
    )
    assert pending2[0]["consumer"] == "alive-node-2"

    # ACK it to clean up
    await redis_client.xack(TEST_STREAM, TEST_GROUP, entry_id)

    # Verify pending is now empty
    pending3 = await redis_client.xpending_range(
        TEST_STREAM, TEST_GROUP, min="-", max="+", count=10
    )
    assert len(pending3) == 0
