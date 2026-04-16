from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from backend.queue.adapters.redis_adapter import RedisProtocolError, RedisQueueAdapter
from backend.queue.base import QueueMessage


def _message() -> QueueMessage:
    return QueueMessage(
        tenant_id="tenant-a",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        fleet_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        payload={"k": "v"},
        enqueued_at=datetime.now(UTC),
    )


def test_ping_returns_true_on_pong(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: "PONG")
    assert adapter.ping() is True


def test_ping_returns_false_on_socket_error(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    def _boom(command):
        raise OSError("down")

    monkeypatch.setattr(adapter, "_execute", _boom)
    assert adapter.ping() is False


def test_enqueue_task_returns_ok_on_integer_reply(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    result = adapter.enqueue_task(_message())

    monkeypatch.setattr(adapter, "_execute", lambda command: 1)

    result = adapter.enqueue_task(_message())

    assert result.ok is True
    assert result.reason is None


def test_enqueue_task_returns_failure_on_non_integer_reply(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: "weird")

    result = adapter.enqueue_task(_message())

    assert result.ok is False
    assert result.reason == "redis did not confirm enqueue"


def test_enqueue_task_returns_failure_on_exception(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    def _boom(command):
        raise RuntimeError("bad push")

    monkeypatch.setattr(adapter, "_execute", _boom)

    result = adapter.enqueue_task(_message())

    assert result.ok is False
    assert result.reason == "enqueue failed: bad push"


def test_claim_task_returns_none_when_queue_empty(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: None)

    result = adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")

    assert result is None


def test_claim_task_raises_on_unexpected_payload_type(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: 123)

    with pytest.raises(RuntimeError, match="claim_task failed"):
        adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")


def test_claim_task_decodes_message_and_touches_lease(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    message = _message()
    raw = adapter._encode_message(message)
    touched: list[tuple[str, uuid.UUID, str]] = []

    monkeypatch.setattr(adapter, "_execute", lambda command: raw)
    monkeypatch.setattr(
        adapter,
        "_touch_lease_key",
        lambda *, tenant_id, task_id, worker_id: touched.append((tenant_id, task_id, worker_id)),
    )

    result = adapter.claim_task(tenant_id="tenant-a", worker_id="worker-1")

    assert result == message
    assert touched == [("tenant-a", message.task_id, "worker-1")]


def test_heartbeat_returns_ok_when_touch_succeeds(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    called: list[tuple[str, uuid.UUID, str]] = []

    monkeypatch.setattr(
        adapter,
        "_touch_lease_key",
        lambda *, tenant_id, task_id, worker_id: called.append((tenant_id, task_id, worker_id)),
    )

    result = adapter.heartbeat(tenant_id="tenant-a", task_id=task_id, worker_id="worker-1")

    assert result.ok is True
    assert called == [("tenant-a", task_id, "worker-1")]


def test_heartbeat_returns_failure_on_exception(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    def _boom(**kwargs):
        raise RuntimeError("touch failed")

    monkeypatch.setattr(adapter, "_touch_lease_key", _boom)

    result = adapter.heartbeat(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")

    assert result.ok is False
    assert result.reason == "heartbeat failed: touch failed"


def test_complete_task_returns_not_found_when_payload_missing(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: None)

    result = adapter.complete_task(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")

    assert result.ok is False
    assert result.reason == "task not found in processing queue"


def test_complete_task_returns_failure_when_lrem_does_not_remove(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: '{"task_id":"x"}')
    monkeypatch.setattr(adapter, "_execute", lambda command: 0 if command[0] == "LREM" else 1)

    result = adapter.complete_task(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")

    assert result.ok is False
    assert result.reason == "processing payload was not removed"


def test_complete_task_returns_ok_when_removed(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: '{"task_id":"x"}')
    monkeypatch.setattr(adapter, "_execute", lambda command: 1)

    result = adapter.complete_task(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")

    assert result.ok is True


def test_fail_task_returns_not_found_when_payload_missing(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: None)

    result = adapter.fail_task(
        tenant_id="tenant-a",
        task_id=uuid.uuid4(),
        worker_id="worker-1",
        reason="boom",
    )

    assert result.ok is False
    assert result.reason == "task not found in processing queue"


def test_fail_task_returns_failure_when_lrem_does_not_remove(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: '{"task_id":"x"}')
    monkeypatch.setattr(adapter, "_execute", lambda command: 0 if command[0] == "LREM" else 1)

    result = adapter.fail_task(
        tenant_id="tenant-a",
        task_id=uuid.uuid4(),
        worker_id="worker-1",
        reason="boom",
    )

    assert result.ok is False
    assert result.reason == "processing payload was not removed"


def test_fail_task_pushes_dead_letter_envelope(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    commands: list[list[str]] = []

    monkeypatch.setattr(
        adapter,
        "_find_processing_payload",
        lambda **kwargs: json.dumps({"task_id": str(task_id), "x": 1}),
    )

    def _execute(command):
        commands.append(command)
        if command[0] == "LREM":
            return 1
        if command[0] in {"LPUSH", "DEL"}:
            return 1
        return 1

    monkeypatch.setattr(adapter, "_execute", _execute)

    result = adapter.fail_task(
        tenant_id="tenant-a",
        task_id=task_id,
        worker_id="worker-1",
        reason="boom",
    )

    assert result.ok is True
    envelope = next(command[2] for command in commands if command[0] == "LPUSH")
    parsed = json.loads(envelope)
    assert parsed["task_id"] == str(task_id)
    assert parsed["worker_id"] == "worker-1"
    assert parsed["reason"] == "boom"


def test_release_lease_returns_failure_when_del_result_is_unexpected(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: None)
    monkeypatch.setattr(adapter, "_execute", lambda command: "bad")

    result = adapter.release_lease(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")

    assert result.ok is False
    assert result.reason == "lease delete returned unexpected result"


def test_release_lease_requeues_payload_when_found(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    commands: list[list[str]] = []

    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: '{"task_id":"x"}')

    def _execute(command):
        commands.append(command)
        if command[0] == "LREM":
            return 1
        if command[0] == "RPUSH":
            return 1
        if command[0] == "DEL":
            return 1
        return 1

    monkeypatch.setattr(adapter, "_execute", _execute)

    result = adapter.release_lease(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")

    assert result.ok is True
    assert [command[0] for command in commands] == ["LREM", "RPUSH", "DEL"]


def test_move_to_dead_letter_returns_not_found_when_payload_missing(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: None)

    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=uuid.uuid4(), reason="bad")

    assert result.ok is False
    assert result.reason == "task not found in processing queue"


def test_move_to_dead_letter_returns_failure_when_lrem_does_not_remove(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_find_processing_payload", lambda **kwargs: '{"task_id":"x"}')
    monkeypatch.setattr(adapter, "_execute", lambda command: 0 if command[0] == "LREM" else 1)

    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=uuid.uuid4(), reason="bad")

    assert result.ok is False
    assert result.reason == "processing payload was not removed"


def test_move_to_dead_letter_pushes_envelope(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    commands: list[list[str]] = []

    monkeypatch.setattr(
        adapter,
        "_find_processing_payload",
        lambda **kwargs: json.dumps({"task_id": str(task_id), "x": 1}),
    )

    def _execute(command):
        commands.append(command)
        if command[0] == "LREM":
            return 1
        if command[0] in {"LPUSH", "DEL"}:
            return 1
        return 1

    monkeypatch.setattr(adapter, "_execute", _execute)

    result = adapter.move_to_dead_letter(tenant_id="tenant-a", task_id=task_id, reason="bad")

    assert result.ok is True
    envelope = next(command[2] for command in commands if command[0] == "LPUSH")
    parsed = json.loads(envelope)
    assert parsed["task_id"] == str(task_id)
    assert parsed["reason"] == "bad"


def test_touch_lease_key_raises_when_set_is_not_ok(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: "NOPE")

    with pytest.raises(RedisProtocolError, match="lease heartbeat SET did not return OK"):
        adapter._touch_lease_key(tenant_id="tenant-a", task_id=uuid.uuid4(), worker_id="worker-1")


def test_find_processing_payload_returns_match_and_skips_bad_json(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    task_id = uuid.uuid4()
    values = [
        123,
        "not-json",
        json.dumps({"task_id": "other"}),
        json.dumps({"task_id": str(task_id), "x": 1}),
    ]
    monkeypatch.setattr(adapter, "_execute", lambda command: values)

    result = adapter._find_processing_payload(tenant_id="tenant-a", task_id=task_id)

    assert result == values[-1]


def test_find_processing_payload_raises_on_non_list_lrange(monkeypatch) -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    monkeypatch.setattr(adapter, "_execute", lambda command: "bad")

    with pytest.raises(RedisProtocolError, match="LRANGE returned unexpected type"):
        adapter._find_processing_payload(tenant_id="tenant-a", task_id=uuid.uuid4())


def test_encode_and_decode_message_round_trip() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")
    message = _message()

    raw = adapter._encode_message(message)
    decoded = adapter._decode_message(raw)

    assert decoded == message


def test_read_response_handles_simple_string() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data
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

    assert adapter._read_response(_FakeFile(b"+PONG\r\n")) == "PONG"


def test_read_response_handles_integer() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data
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

    assert adapter._read_response(_FakeFile(b":5\r\n")) == 5


def test_read_response_handles_bulk_string_and_array() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data
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

    assert adapter._read_response(_FakeFile(b"$4\r\nPONG\r\n")) == "PONG"
    assert adapter._read_response(_FakeFile(b"*2\r\n+OK\r\n:1\r\n")) == ["OK", 1]


def test_read_response_raises_on_error_prefix() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data
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

    with pytest.raises(RedisProtocolError, match="ERR boom"):
        adapter._read_response(_FakeFile(b"-ERR boom\r\n"))


def test_read_response_raises_on_unsupported_prefix() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data
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

    with pytest.raises(RedisProtocolError, match="unsupported Redis response prefix"):
        adapter._read_response(_FakeFile(b"!wat\r\n"))


def test_read_line_raises_on_malformed_response() -> None:
    adapter = RedisQueueAdapter("redis://localhost:6379/0")

    class _FakeFile:
        def readline(self) -> bytes:
            return b"bad-line"

    with pytest.raises(RedisProtocolError, match="malformed Redis line response"):
        adapter._read_line(_FakeFile())
