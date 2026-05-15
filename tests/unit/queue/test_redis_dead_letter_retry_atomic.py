from __future__ import annotations

import uuid

from backend.queue.adapters.redis_adapter import RedisQueueAdapter


def test_retry_dead_letter_uses_single_eval_command(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    calls: list[list[str]] = []

    def _execute(command: list[str]):
        calls.append(command)
        return [1, "ok"]

    monkeypatch.setattr(adapter, "_execute", _execute)

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=task_id)

    assert result.ok is True
    assert result.reason is None
    assert len(calls) == 1
    command = calls[0]
    assert command[0] == "EVAL"
    assert command[2] == "3"
    assert command[3] == "ajenda:queue:tenant-a:pending"
    assert command[4] == "ajenda:queue:tenant-a:processing"
    assert command[5] == "ajenda:queue:tenant-a:dead_letter"
    assert command[6:] == ["tenant-a", str(task_id)]


def test_retry_dead_letter_script_failure_returns_reason(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    calls: list[list[str]] = []

    def _execute(command: list[str]):
        calls.append(command)
        return [0, "task already pending"]

    monkeypatch.setattr(adapter, "_execute", _execute)

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=task_id)

    assert result.ok is False
    assert result.reason == "task already pending"
    assert len(calls) == 1
    assert calls[0][0] == "EVAL"


def test_retry_dead_letter_unexpected_script_result_fails_closed(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()

    monkeypatch.setattr(adapter, "_execute", lambda command: "OK")

    result = adapter.retry_dead_letter(tenant_id="tenant-a", task_id=task_id)

    assert result.ok is False
    assert result.reason == "retry script returned unexpected result"
