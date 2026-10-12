from __future__ import annotations

import uuid

import pytest

from backend.queue.adapters.redis_adapter import RedisQueueAdapter


def _capture(
    monkeypatch: pytest.MonkeyPatch,
    adapter: RedisQueueAdapter,
    operation_response: object,
) -> list[list[str]]:
    calls: list[list[str]] = []
    responses = iter(([1, "ready"], operation_response))

    def _execute(command: list[str]) -> object:
        calls.append(command)
        return next(responses)

    monkeypatch.setattr(adapter, "_execute", _execute)
    return calls


def test_retry_dead_letter_uses_indexed_atomic_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    calls = _capture(monkeypatch, adapter, [1, "ok"])

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=task_id)

    assert result.ok is True
    command = calls[1]
    assert command[0:3] == ["EVAL", adapter._RETRY_DEAD_LETTER_SCRIPT, "6"]
    assert command[3:9] == [
        "ajenda:queue:tenant-a:v2:pending-order",
        "ajenda:queue:tenant-a:v2:pending-payloads",
        "ajenda:queue:tenant-a:v2:processing-payloads",
        "ajenda:queue:tenant-a:v2:dead-letter-order",
        "ajenda:queue:tenant-a:v2:dead-letter-payloads",
        "ajenda:queue:tenant-a:v2:sequence",
    ]
    assert command[9:] == ["tenant-a", str(task_id)]


def test_retry_dead_letter_preserves_script_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    _capture(monkeypatch, adapter, [0, "task already pending"])

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=uuid.uuid4())

    assert result.ok is False
    assert result.reason == "task already pending"


def test_retry_dead_letter_unexpected_result_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    _capture(monkeypatch, adapter, "OK")

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=uuid.uuid4())

    assert result.ok is False
    assert result.reason == "retry script returned unexpected result"


def test_retry_dead_letter_validates_exact_indexed_payload() -> None:
    script = RedisQueueAdapter._RETRY_DEAD_LETTER_SCRIPT

    assert 'redis.call("HGET", dead_payloads, task_id)' in script
    assert 'redis.call("HDEL", dead_payloads, task_id)' in script
    assert 'redis.call("ZREM", dead_order, task_id)' in script
    assert "invalid envelope" in script
    assert "tenant_id mismatch" in script
    assert "task_id mismatch" in script
    assert "missing mission_id" in script
    assert "missing payload" in script
    assert "missing enqueued_at" in script
    assert 'redis.call("LRANGE"' not in script
    assert 'redis.call("LREM"' not in script
