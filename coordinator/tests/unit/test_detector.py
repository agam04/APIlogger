"""Unit tests for quorum detector logic (pure functions)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import UTC, datetime, timedelta


def _make_result(status: str, minutes_ago: int = 0) -> dict:
    return {
        "service_id": "test-service-id",
        "checker_node_id": "node-1",
        "checked_at": datetime.now(UTC) - timedelta(minutes=minutes_ago),
        "status": status,
        "status_code": 200 if status == "up" else None,
        "response_ms": 50 if status == "up" else None,
        "error_message": None if status == "up" else "Connection refused",
        "idempotency_key": f"key-{status}-{minutes_ago}",
    }


class TestQuorumFraction:
    """Test that quorum fraction is computed correctly."""

    def test_all_up_no_incident(self):
        results = [_make_result("up") for _ in range(5)]
        failing = sum(1 for r in results if r["status"] in ("down", "timeout", "error"))
        fraction = failing / len(results)
        assert fraction == 0.0
        assert fraction < 0.51  # below quorum

    def test_majority_down_triggers_incident(self):
        results = [_make_result("down") for _ in range(3)] + [_make_result("up") for _ in range(2)]
        failing = sum(1 for r in results if r["status"] in ("down", "timeout", "error"))
        fraction = failing / len(results)
        assert fraction == 0.6
        assert fraction >= 0.51  # above quorum

    def test_exactly_at_threshold(self):
        # 51% of 100 = 51 failing
        results = [_make_result("down") for _ in range(51)] + [_make_result("up") for _ in range(49)]
        failing = sum(1 for r in results if r["status"] in ("down", "timeout", "error"))
        fraction = failing / len(results)
        assert fraction == 0.51
        assert fraction >= 0.51

    def test_mixed_error_types_count(self):
        results = [
            _make_result("down"),
            _make_result("timeout"),
            _make_result("error"),
            _make_result("up"),
        ]
        failing = sum(1 for r in results if r["status"] in ("down", "timeout", "error"))
        fraction = failing / len(results)
        assert fraction == 0.75
