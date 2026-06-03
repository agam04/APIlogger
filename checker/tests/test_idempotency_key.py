"""Test that the idempotency key construction is stable and unique."""

from app.reporter import _build_idempotency_key


def test_same_inputs_same_key():
    k1 = _build_idempotency_key("svc-1", "node-a", 42)
    k2 = _build_idempotency_key("svc-1", "node-a", 42)
    assert k1 == k2


def test_different_service_different_key():
    k1 = _build_idempotency_key("svc-1", "node-a", 42)
    k2 = _build_idempotency_key("svc-2", "node-a", 42)
    assert k1 != k2


def test_different_node_different_key():
    k1 = _build_idempotency_key("svc-1", "node-a", 42)
    k2 = _build_idempotency_key("svc-1", "node-b", 42)
    assert k1 != k2


def test_different_round_different_key():
    k1 = _build_idempotency_key("svc-1", "node-a", 42)
    k2 = _build_idempotency_key("svc-1", "node-a", 43)
    assert k1 != k2


def test_key_format():
    k = _build_idempotency_key("my-service", "my-node", 100)
    assert "my-service" in k
    assert "my-node" in k
    assert "100" in k
