from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.queue.adapters.redis_adapter import RedisProtocolError, RedisQueueAdapter
from backend.queue.base import QueueMessage


def _message(tenant_id: str = "tenant-a") -> QueueMessage:
    return QueueMessage(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        fleet_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        payload={"k": "v"},
        enqueued_at=datetime.now(UTC),
    )


def _capture(
    monkeypatch: pytest.MonkeyPatch,
    adapter: RedisQueueAdapter,
    *responses: object,
) -> list[list[str]]:
    calls: list[list[str]] = []
    remaining = iter(responses)

    def _execute(command: list[str]) -> object:
        calls.append(command)
        return next(remaining)

    monkeypatch.setattr(adapter, "_execute", _execute)
    return calls


def _fake_file(data: bytes) -> Any:
    class _FakeFile:
        def __init__(self, content: bytes) -> None:
            self._data = content
            self._pos = 0

        def read(self, n: int = -1) -> bytes:
            if n == -1:
                n = len(self._data) - self._pos
            chunk = self._data[self._pos : self._pos + n]
            self._pos += len(chunk)
            return chunk

        def readline(self) -> bytes:
            idx = self._data.index(b"\r\n", self._pos) + 2
            chunk = self._data[self._pos : idx]
            self._pos = idx
            return chunk

    return _FakeFile(data)


def test_requires_redis_url() -> None:
    with pytest.raises(ValueError, match="redis://"):
        RedisQueueAdapter("http://localhost:6379/0")


def test_pending_depth_uses_index_cardinality(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    calls = _capture(monkeypatch, adapter, [1, "ready"], 3)

    assert adapter.pending_depth(tenant_id="tenant-a") == 3
    assert calls[1] == ["ZCARD", "ajenda:queue:tenant-a:v2:pending-order"]


def test_pending_depth_returns_zero_when_redis_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: (_ for _ in ()).throw(OSError("down")))

    assert adapter.pending_depth(tenant_id="tenant-a") == 0


def test_ping_reports_redis_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: "PONG")
    assert adapter.ping() is True

    monkeypatch.setattr(adapter, "_execute", lambda command: (_ for _ in ()).throw(OSError("down")))
    assert adapter.ping() is False


def test_schema_gate_uses_all_legacy_and_indexed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    calls = _capture(monkeypatch, adapter, [1, "migrated"])

    adapter._ensure_queue_schema("tenant-a")

    assert calls == [
        [
            "EVAL",
            adapter._MIGRATE_LEGACY_SCRIPT,
            "10",
            "ajenda:queue:tenant-a:pending",
            "ajenda:queue:tenant-a:processing",
            "ajenda:queue:tenant-a:dead_letter",
            "ajenda:queue:tenant-a:v2:pending-order",
            "ajenda:queue:tenant-a:v2:pending-payloads",
            "ajenda:queue:tenant-a:v2:processing-payloads",
            "ajenda:queue:tenant-a:v2:dead-letter-order",
            "ajenda:queue:tenant-a:v2:dead-letter-payloads",
            "ajenda:queue:tenant-a:v2:sequence",
            "ajenda:queue:tenant-a:v2:schema",
            "tenant-a",
        ]
    ]


def test_schema_gate_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    _capture(monkeypatch, adapter, [0, "legacy pending payload tenant mismatch"])

    with pytest.raises(RedisProtocolError, match="tenant mismatch"):
        adapter._ensure_queue_schema("tenant-a")


def test_enqueue_uses_indexed_atomic_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    message = _message()
    calls = _capture(monkeypatch, adapter, [1, "ready"], [1, "published"])

    result = adapter.enqueue_task(message)

    assert result.ok is True
    assert calls[1][0:3] == ["EVAL", adapter._ENQUEUE_SCRIPT, "4"]
    assert calls[1][3:7] == [
        "ajenda:queue:tenant-a:v2:pending-order",
        "ajenda:queue:tenant-a:v2:pending-payloads",
        "ajenda:queue:tenant-a:v2:processing-payloads",
        "ajenda:queue:tenant-a:v2:sequence",
    ]
    assert calls[1][7] == str(message.task_id)


def test_enqueue_fails_closed_on_bad_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    _capture(monkeypatch, adapter, [1, "ready"], "unexpected")

    result = adapter.enqueue_task(_message())

    assert result.ok is False
    assert result.reason == "enqueue script returned unexpected result"


def test_idempotent_enqueue_uses_stable_dispatch_key(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    message = _message()
    calls = _capture(monkeypatch, adapter, [1, "ready"], [1, "published"])

    result = adapter.enqueue_task_idempotent(message, idempotency_key="dispatch-1")

    assert result.ok is True
    command = calls[1]
    assert command[0:3] == ["EVAL", adapter._IDEMPOTENT_ENQUEUE_SCRIPT, "5"]
    assert command[7] == "ajenda:queue:tenant-a:dispatch:dispatch-1"


def test_cancel_checks_processing_and_removes_by_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    calls = _capture(monkeypatch, adapter, [1, "ready"], [1, "cancelled"])

    result = adapter.cancel_task(tenant_id="tenant-a", task_id=task_id)

    assert result.ok is True
    assert calls[1][0:3] == ["EVAL", adapter._CANCEL_PENDING_TASK_SCRIPT, "3"]
    assert calls[1][-1] == str(task_id)


def test_claim_returns_none_for_empty_index(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    calls = _capture(monkeypatch, adapter, [1, "ready"], [0, "empty"])

    assert adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1") is None
    assert calls[1][0:3] == ["EVAL", adapter._CLAIM_NEXT_TASK_SCRIPT, "3"]


def test_claim_decodes_payload_and_sets_owner_atomically(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    message = _message()
    calls = _capture(monkeypatch, adapter, [1, "ready"], [1, adapter._encode_message(message)])

    claimed = adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")

    assert claimed == message
    assert calls[1][-3:] == ["ajenda:queue:tenant-a:lease:", "worker-1", "90"]


def test_claim_raises_on_protocol_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    _capture(monkeypatch, adapter, [1, "ready"], 123)

    with pytest.raises(RuntimeError, match="claim script returned unexpected result"):
        adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")


@pytest.mark.parametrize(
    ("method_name", "script_name", "key_count", "kwargs"),
    [
        ("claim_existing_task", "_CLAIM_EXISTING_TASK_SCRIPT", "4", {}),
        ("heartbeat", "_HEARTBEAT_OWNER_SCRIPT", "1", {}),
        ("complete_task", "_COMPLETE_OWNER_SCRIPT", "2", {}),
        ("fail_task", "_FAIL_OWNER_SCRIPT", "5", {"reason": "boom"}),
        ("release_lease", "_RELEASE_OWNER_SCRIPT", "5", {}),
        ("recover_task_for_retry", "_RECOVER_OWNER_SCRIPT", "5", {}),
        ("move_owned_to_dead_letter", "_DEAD_LETTER_SCRIPT", "7", {"reason": "abandoned"}),
    ],
)
def test_owner_sensitive_transitions_are_atomic_evals(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    script_name: str,
    key_count: str,
    kwargs: dict[str, str],
) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    calls = _capture(monkeypatch, adapter, [1, "ready"], [1, "ok"])

    result = getattr(adapter, method_name)(
        tenant_id="tenant-a",
        task_id=task_id,
        worker_id="worker-1",
        **kwargs,
    )

    assert result.ok is True
    assert calls[1][0:3] == ["EVAL", getattr(adapter, script_name), key_count]


def test_transition_failure_preserves_script_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    _capture(monkeypatch, adapter, [1, "ready"], [0, "worker does not own claim"])

    result = adapter.complete_task(
        tenant_id="tenant-a",
        task_id=uuid.uuid4(),
        worker_id="worker-2",
    )

    assert result.ok is False
    assert result.reason == "worker does not own claim"


def test_schema_failure_prevents_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    calls = _capture(monkeypatch, adapter, [0, "legacy queue received data after indexed migration"])

    result = adapter.complete_task(
        tenant_id="tenant-a",
        task_id=uuid.uuid4(),
        worker_id="worker-1",
    )

    assert result.ok is False
    assert "legacy queue received data" in (result.reason or "")
    assert len(calls) == 1


def test_list_processing_reports_corruption_and_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    other = _message("tenant-b")
    _capture(
        monkeypatch,
        adapter,
        [1, "ready"],
        ["not-json", adapter._encode_message(other)],
    )

    entries = adapter.list_processing(tenant_id="tenant-a")

    assert len(entries) == 2
    assert entries[0].error and "corrupt" in entries[0].error
    assert entries[1].error == "processing payload tenant mismatch"


def test_list_dead_letter_returns_only_tenant_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    valid = json.dumps(
        {
            "task_id": str(task_id),
            "reason": "boom",
            "payload": {"tenant_id": "tenant-a"},
        }
    )
    other = json.dumps(
        {
            "task_id": str(uuid.uuid4()),
            "reason": "other",
            "payload": {"tenant_id": "tenant-b"},
        }
    )
    _capture(monkeypatch, adapter, [1, "ready"], ["not-json", other, valid])

    entries = adapter.list_dead_letter(tenant_id="tenant-a")

    assert len(entries) == 2
    assert entries[0].error and "corrupt" in entries[0].error
    assert entries[1].task_id == task_id
    assert entries[1].reason == "boom"


def test_task_specific_scripts_do_not_scan_queue_collections() -> None:
    scripts = [
        RedisQueueAdapter._ENQUEUE_SCRIPT,
        RedisQueueAdapter._IDEMPOTENT_ENQUEUE_SCRIPT,
        RedisQueueAdapter._CANCEL_PENDING_TASK_SCRIPT,
        RedisQueueAdapter._CLAIM_EXISTING_TASK_SCRIPT,
        RedisQueueAdapter._HEARTBEAT_OWNER_SCRIPT,
        RedisQueueAdapter._COMPLETE_OWNER_SCRIPT,
        RedisQueueAdapter._FAIL_OWNER_SCRIPT,
        RedisQueueAdapter._RELEASE_OWNER_SCRIPT,
        RedisQueueAdapter._RECOVER_OWNER_SCRIPT,
        RedisQueueAdapter._DEAD_LETTER_SCRIPT,
        RedisQueueAdapter._RETRY_DEAD_LETTER_SCRIPT,
    ]

    for script in scripts:
        assert 'redis.call("LRANGE"' not in script
        assert 'redis.call("LREM"' not in script
        assert 'redis.call("HVALS"' not in script
    assert 'redis.call("ZRANGE", pending_order, 0, 0)' in RedisQueueAdapter._CLAIM_NEXT_TASK_SCRIPT


def test_migration_is_the_only_script_allowed_to_scan_legacy_lists() -> None:
    script = RedisQueueAdapter._MIGRATE_LEGACY_SCRIPT

    assert 'redis.call("LRANGE", legacy_pending, 0, -1)' in script
    assert 'redis.call("LRANGE", legacy_processing, 0, -1)' in script
    assert 'redis.call("LRANGE", legacy_dead, 0, -1)' in script
    assert "payload tenant mismatch" in script
    assert 'redis.call("SET", schema_key, "indexed-v2")' in script


def test_encode_and_decode_message_round_trip() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    message = _message()

    assert adapter._decode_message(adapter._encode_message(message)) == message


def test_read_response_handles_redis_types() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    assert adapter._read_response(_fake_file(b"+PONG\r\n")) == "PONG"
    assert adapter._read_response(_fake_file(b":5\r\n")) == 5
    assert adapter._read_response(_fake_file(b"$4\r\nPONG\r\n")) == "PONG"
    assert adapter._read_response(_fake_file(b"*2\r\n+OK\r\n:1\r\n")) == ["OK", 1]


def test_read_response_rejects_errors_and_unknown_types() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    with pytest.raises(RedisProtocolError, match="ERR boom"):
        adapter._read_response(_fake_file(b"-ERR boom\r\n"))
    with pytest.raises(RedisProtocolError, match="unsupported Redis response prefix"):
        adapter._read_response(_fake_file(b"!wat\r\n"))


def test_read_line_rejects_malformed_response() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def readline(self) -> bytes:
            return b"bad-line"

    with pytest.raises(RedisProtocolError, match="malformed Redis line response"):
        adapter._read_line(_FakeFile())
