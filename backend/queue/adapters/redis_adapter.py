from __future__ import annotations

import json
import socket
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from backend.queue.base import (
    QueueAdapter,
    QueueDeadLetterEntry,
    QueueMessage,
    QueueOperationResult,
    QueuePayloadInspection,
)


class RedisProtocolError(RuntimeError):
    """Raised when Redis returns an unexpected protocol response."""


class RedisQueueAdapter(QueueAdapter):
    """Redis-backed list queue adapter.

    Queue model:
    - pending list:    ajenda:queue:{tenant_id}:pending
    - processing list: ajenda:queue:{tenant_id}:processing
    - dead-letter list: ajenda:queue:{tenant_id}:dead_letter
    - heartbeat key:   ajenda:queue:{tenant_id}:lease:{task_id}

    This adapter is intentionally strict:
    - ping() performs a real Redis PING
    - mutating methods fail closed on Redis errors
    - claim_task() returns None only when Redis checked the queue and it was empty
    """

    _RECOVER_TASK_FOR_RETRY_SCRIPT = """
local processing_key = KEYS[1]
local pending_key = KEYS[2]
local lease_key = KEYS[3]
local task_id = ARGV[1]

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" then
        return nil
    end
    if payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local processing_values = redis.call("LRANGE", processing_key, 0, -1)
local pending_values = redis.call("LRANGE", pending_key, 0, -1)
local canonical_payload = nil
local kept_processing = {}
local kept_pending = {}

for _, raw in ipairs(pending_values) do
    if payload_task_id(raw) == task_id then
        if canonical_payload == nil then
            canonical_payload = raw
        end
    else
        table.insert(kept_pending, raw)
    end
end

for _, raw in ipairs(processing_values) do
    if payload_task_id(raw) == task_id then
        if canonical_payload == nil then
            canonical_payload = raw
        end
    else
        table.insert(kept_processing, raw)
    end
end

if canonical_payload == nil then
    return {0, "task not found in processing or pending queue"}
end

table.insert(kept_pending, canonical_payload)
redis.call("DEL", processing_key)
redis.call("DEL", pending_key)

for _, raw in ipairs(kept_processing) do
    redis.call("RPUSH", processing_key, raw)
end
for _, raw in ipairs(kept_pending) do
    redis.call("RPUSH", pending_key, raw)
end
redis.call("DEL", lease_key)
return {1, "ok"}
"""

    _CLAIM_EXISTING_TASK_SCRIPT = """
local pending_key = KEYS[1]
local processing_key = KEYS[2]
local lease_key = KEYS[3]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = ARGV[3]

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" then
        return nil
    end
    if payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local processing_values = redis.call("LRANGE", processing_key, 0, -1)
for _, raw in ipairs(processing_values) do
    if payload_task_id(raw) == task_id then
        local owner = redis.call("GET", lease_key)
        if owner == false then
            return {0, "processing payload has no worker owner"}
        end
        if owner ~= worker_id then
            return {0, "task already claimed by different worker"}
        end
        redis.call("SET", lease_key, worker_id, "EX", ttl_seconds)
        return {1, "ok"}
    end
end

local pending_values = redis.call("LRANGE", pending_key, 0, -1)
local claimed_payload = nil
local kept_pending = {}

for _, raw in ipairs(pending_values) do
    if claimed_payload == nil and payload_task_id(raw) == task_id then
        claimed_payload = raw
    else
        table.insert(kept_pending, raw)
    end
end

if claimed_payload == nil then
    return {0, "task not found in pending or processing queue"}
end

redis.call("DEL", pending_key)
for _, raw in ipairs(kept_pending) do
    redis.call("RPUSH", pending_key, raw)
end
redis.call("RPUSH", processing_key, claimed_payload)
redis.call("SET", lease_key, worker_id, "EX", ttl_seconds)
return {1, "ok"}
"""

    _RETRY_DEAD_LETTER_SCRIPT = """
local pending_key = KEYS[1]
local processing_key = KEYS[2]
local dead_letter_key = KEYS[3]
local tenant_id = ARGV[1]
local task_id = ARGV[2]

local function key_type(key)
    local result = redis.call("TYPE", key)
    if type(result) == "table" then
        return result["ok"]
    end
    return result
end

local function ensure_list_or_none(key, name)
    local current_type = key_type(key)
    if current_type ~= "none" and current_type ~= "list" then
        return false, name .. " key is not a list"
    end
    return true, "ok"
end

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" then
        return nil
    end
    if payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local function validate_queue_message(payload)
    if type(payload) ~= "table" then
        return false, "dead-letter payload is corrupt: payload is not an object"
    end
    if payload["tenant_id"] == nil or tostring(payload["tenant_id"]) ~= tenant_id then
        return false, "dead-letter payload is corrupt: tenant_id mismatch"
    end
    if payload["task_id"] == nil or tostring(payload["task_id"]) ~= task_id then
        return false, "dead-letter payload is corrupt: task_id mismatch"
    end
    if payload["mission_id"] == nil then
        return false, "dead-letter payload is corrupt: missing mission_id"
    end
    if payload["payload"] == nil or type(payload["payload"]) ~= "table" then
        return false, "dead-letter payload is corrupt: missing payload"
    end
    if payload["enqueued_at"] == nil then
        return false, "dead-letter payload is corrupt: missing enqueued_at"
    end
    return true, "ok"
end

local pending_ok, pending_reason = ensure_list_or_none(pending_key, "pending")
if not pending_ok then
    return {0, pending_reason}
end
local processing_ok, processing_reason = ensure_list_or_none(processing_key, "processing")
if not processing_ok then
    return {0, processing_reason}
end
local dead_letter_ok, dead_letter_reason = ensure_list_or_none(dead_letter_key, "dead-letter")
if not dead_letter_ok then
    return {0, dead_letter_reason}
end

local pending_values = redis.call("LRANGE", pending_key, 0, -1)
for _, raw in ipairs(pending_values) do
    if payload_task_id(raw) == task_id then
        return {0, "task already pending"}
    end
end

local processing_values = redis.call("LRANGE", processing_key, 0, -1)
for _, raw in ipairs(processing_values) do
    if payload_task_id(raw) == task_id then
        return {0, "task already processing"}
    end
end

local dead_letter_values = redis.call("LRANGE", dead_letter_key, 0, -1)
for _, raw in ipairs(dead_letter_values) do
    local envelope_ok, envelope = pcall(cjson.decode, raw)
    if envelope_ok and type(envelope) == "table" then
        local payload = envelope["payload"]
        if type(payload) == "table"
            and tostring(payload["tenant_id"]) == tenant_id
            and tostring(envelope["task_id"]) == task_id then
            local valid, validation_reason = validate_queue_message(payload)
            if not valid then
                return {0, validation_reason}
            end
            local pending_payload = cjson.encode(payload)
            local removed = redis.call("LREM", dead_letter_key, 1, raw)
            if removed < 1 then
                return {0, "dead-letter entry not found"}
            end
            redis.call("RPUSH", pending_key, pending_payload)
            return {1, "ok"}
        end
    end
end

return {0, "dead-letter entry not found"}
"""

    def __init__(self, redis_url: str, *, heartbeat_ttl_seconds: int = 90, block_seconds: int = 1) -> None:
        parsed = urlparse(redis_url)
        if parsed.scheme != "redis":
            raise ValueError("Redis queue adapter requires redis:// URL")
        self._host = parsed.hostname or "redis"
        self._port = parsed.port or 6379
        self._db = int((parsed.path or "/0").lstrip("/") or "0")
        self._password = parsed.password
        self._heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self._block_seconds = block_seconds

    def ping(self) -> bool:
        try:
            response = self._execute(["PING"])
        except OSError:
            return False
        return bool(response == "PONG")

    def enqueue_task(self, message: QueueMessage) -> QueueOperationResult:
        try:
            payload = self._encode_message(message)
            result = self._execute(["RPUSH", self._pending_key(message.tenant_id), payload])
            if not isinstance(result, int):
                return QueueOperationResult(ok=False, reason="redis did not confirm enqueue")
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"enqueue failed: {exc}")

    def claim_task(self, *, tenant_id: str, worker_id: str) -> QueueMessage | None:
        try:
            result = self._execute(
                [
                    "BLMOVE",
                    self._pending_key(tenant_id),
                    self._processing_key(tenant_id),
                    "LEFT",
                    "RIGHT",
                    str(self._block_seconds),
                ]
            )
            if result is None:
                return None
            if not isinstance(result, str):
                raise RedisProtocolError("claim returned unexpected payload type")
            message = self._decode_message(result)
            self._touch_lease_key(tenant_id=tenant_id, task_id=message.task_id, worker_id=worker_id)
            return message
        except Exception as exc:
            raise RuntimeError(f"claim_task failed: {exc}") from exc

    def claim_existing_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._CLAIM_EXISTING_TASK_SCRIPT,
                    "3",
                    self._pending_key(tenant_id),
                    self._processing_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    worker_id,
                    str(self._heartbeat_ttl_seconds),
                ]
            )
            if not isinstance(result, list) or len(result) != 2:
                return QueueOperationResult(ok=False, reason="claim script returned unexpected result")
            ok, reason = result
            if ok != 1:
                return QueueOperationResult(ok=False, reason=str(reason))
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"claim_existing_task failed: {exc}")

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            self._touch_lease_key(tenant_id=tenant_id, task_id=task_id, worker_id=worker_id)
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"heartbeat failed: {exc}")

    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            payload = self._find_processing_payload(tenant_id=tenant_id, task_id=task_id)
            if payload is None:
                return QueueOperationResult(ok=False, reason="task not found in processing queue")
            removed = self._execute(["LREM", self._processing_key(tenant_id), "1", payload])
            self._execute(["DEL", self._lease_key(tenant_id, task_id)])
            if not isinstance(removed, int) or removed < 1:
                return QueueOperationResult(ok=False, reason="processing payload was not removed")
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"complete_task failed: {exc}")

    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        try:
            payload = self._find_processing_payload(tenant_id=tenant_id, task_id=task_id)
            if payload is None:
                return QueueOperationResult(ok=False, reason="task not found in processing queue")
            removed = self._execute(["LREM", self._processing_key(tenant_id), "1", payload])
            if not isinstance(removed, int) or removed < 1:
                return QueueOperationResult(ok=False, reason="processing payload was not removed")
            failed_envelope = json.dumps(
                {
                    "task_id": str(task_id),
                    "worker_id": worker_id,
                    "reason": reason,
                    "failed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "payload": json.loads(payload),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            self._execute(["LPUSH", self._dead_letter_key(tenant_id), failed_envelope])
            self._execute(["DEL", self._lease_key(tenant_id, task_id)])
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"fail_task failed: {exc}")

    def release_lease(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            payload = self._find_processing_payload(tenant_id=tenant_id, task_id=task_id)
            if payload is None:
                return QueueOperationResult(ok=False, reason="task not found in processing queue")
            removed = self._execute(["LREM", self._processing_key(tenant_id), "1", payload])
            if not isinstance(removed, int) or removed < 1:
                return QueueOperationResult(ok=False, reason="processing payload was not removed")
            requeued = self._execute(["RPUSH", self._pending_key(tenant_id), payload])
            if not isinstance(requeued, int):
                return QueueOperationResult(ok=False, reason="redis did not confirm requeue")
            deleted = self._execute(["DEL", self._lease_key(tenant_id, task_id)])
            if not isinstance(deleted, int):
                return QueueOperationResult(ok=False, reason="lease delete returned unexpected result")
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"release_lease failed: {exc}")

    def recover_task_for_retry(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._RECOVER_TASK_FOR_RETRY_SCRIPT,
                    "3",
                    self._processing_key(tenant_id),
                    self._pending_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                ]
            )
            if not isinstance(result, list) or len(result) != 2:
                return QueueOperationResult(ok=False, reason="recovery script returned unexpected result")
            ok, reason = result
            if ok != 1:
                return QueueOperationResult(ok=False, reason=str(reason))
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"recover_task_for_retry failed: {exc}")

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        try:
            payload = self._find_processing_payload(tenant_id=tenant_id, task_id=task_id)
            if payload is not None:
                removed = self._execute(["LREM", self._processing_key(tenant_id), "1", payload])
                if not isinstance(removed, int) or removed < 1:
                    return QueueOperationResult(ok=False, reason="processing payload was not removed")
                envelope_payload: Any = json.loads(payload)
            else:
                pending_payload = self._find_pending_payload(tenant_id=tenant_id, task_id=task_id)
                if pending_payload is not None:
                    removed = self._execute(["LREM", self._pending_key(tenant_id), "1", pending_payload])
                    if not isinstance(removed, int) or removed < 1:
                        return QueueOperationResult(ok=False, reason="pending payload was not removed")
                    envelope_payload = json.loads(pending_payload)
                else:
                    envelope_payload = {
                        "tenant_id": tenant_id,
                        "task_id": str(task_id),
                        "source": "runtime_recovery_without_processing_payload",
                    }
            envelope = json.dumps(
                {
                    "task_id": str(task_id),
                    "reason": reason,
                    "moved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "payload": envelope_payload,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            self._execute(["LPUSH", self._dead_letter_key(tenant_id), envelope])
            self._execute(["DEL", self._lease_key(tenant_id, task_id)])
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"move_to_dead_letter failed: {exc}")

    def list_processing(self, *, tenant_id: str) -> list[QueuePayloadInspection]:
        try:
            inspections: list[QueuePayloadInspection] = []
            for raw in self._list_payloads(self._processing_key(tenant_id)):
                try:
                    message = self._decode_message(raw)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    inspections.append(
                        QueuePayloadInspection(
                            tenant_id=tenant_id,
                            raw=raw,
                            message=None,
                            error=f"processing payload is corrupt: {exc}",
                        )
                    )
                    continue
                if message.tenant_id != tenant_id:
                    inspections.append(
                        QueuePayloadInspection(
                            tenant_id=tenant_id,
                            raw=raw,
                            message=message,
                            error="processing payload tenant mismatch",
                        )
                    )
                    continue
                inspections.append(QueuePayloadInspection(tenant_id=tenant_id, raw=raw, message=message))
            return inspections
        except Exception as exc:
            raise RuntimeError(f"list_processing failed: {exc}") from exc

    def list_dead_letter(self, *, tenant_id: str) -> list[QueueDeadLetterEntry]:
        try:
            entries: list[QueueDeadLetterEntry] = []
            for raw in self._list_payloads(self._dead_letter_key(tenant_id)):
                try:
                    envelope = json.loads(raw)
                except json.JSONDecodeError as exc:
                    entries.append(
                        QueueDeadLetterEntry(
                            tenant_id=tenant_id,
                            task_id=None,
                            raw=raw,
                            error=f"dead-letter payload is corrupt: {exc}",
                        )
                    )
                    continue
                if not isinstance(envelope, dict):
                    entries.append(
                        QueueDeadLetterEntry(
                            tenant_id=tenant_id,
                            task_id=None,
                            raw=raw,
                            error="dead-letter payload is not an object",
                        )
                    )
                    continue
                payload = envelope.get("payload")
                payload_tenant = payload.get("tenant_id") if isinstance(payload, dict) else None
                if payload_tenant != tenant_id:
                    continue
                task_id: uuid.UUID | None = None
                error: str | None = None
                try:
                    task_id = uuid.UUID(str(envelope.get("task_id")))
                except (TypeError, ValueError):
                    error = "dead-letter envelope has invalid task_id"
                entries.append(
                    QueueDeadLetterEntry(
                        tenant_id=tenant_id,
                        task_id=task_id,
                        raw=raw,
                        payload=envelope,
                        reason=str(envelope.get("reason")) if envelope.get("reason") is not None else None,
                        error=error,
                    )
                )
            return entries
        except Exception as exc:
            raise RuntimeError(f"list_dead_letter failed: {exc}") from exc

    def retry_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._RETRY_DEAD_LETTER_SCRIPT,
                    "3",
                    self._pending_key(tenant_id),
                    self._processing_key(tenant_id),
                    self._dead_letter_key(tenant_id),
                    tenant_id,
                    str(task_id),
                ]
            )
            if not isinstance(result, list) or len(result) != 2:
                return QueueOperationResult(ok=False, reason="retry script returned unexpected result")
            ok, reason = result
            if ok != 1:
                return QueueOperationResult(ok=False, reason=str(reason))
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"retry_dead_letter failed: {exc}")

    def _touch_lease_key(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> None:
        result = self._execute(
            [
                "SET",
                self._lease_key(tenant_id, task_id),
                worker_id,
                "EX",
                str(self._heartbeat_ttl_seconds),
            ]
        )
        if result != "OK":
            raise RedisProtocolError("lease heartbeat SET did not return OK")

    def _find_processing_payload(self, *, tenant_id: str, task_id: uuid.UUID) -> str | None:
        return self._find_payload(
            key=self._processing_key(tenant_id),
            task_id=task_id,
        )

    def _find_pending_payload(self, *, tenant_id: str, task_id: uuid.UUID) -> str | None:
        return self._find_payload(
            key=self._pending_key(tenant_id),
            task_id=task_id,
        )

    def _find_payload(self, *, key: str, task_id: uuid.UUID) -> str | None:
        payloads = self._find_payloads(key=key, task_id=task_id)
        return payloads[0] if payloads else None

    def _find_payloads(self, *, key: str, task_id: uuid.UUID) -> list[str]:
        task_id_str = str(task_id)
        return [payload for payload in self._list_payloads(key) if self._payload_task_id(payload) == task_id_str]

    def _list_payloads(self, key: str) -> list[str]:
        values = self._execute(["LRANGE", key, "0", "-1"])
        if not isinstance(values, list):
            raise RedisProtocolError("LRANGE returned unexpected type")
        return [item for item in values if isinstance(item, str)]

    def _payload_task_id(self, raw: str) -> str | None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        value = payload.get("task_id")
        return str(value) if value is not None else None

    def _encode_message(self, message: QueueMessage) -> str:
        return json.dumps(
            {
                "tenant_id": message.tenant_id,
                "task_id": str(message.task_id),
                "mission_id": str(message.mission_id),
                "fleet_id": str(message.fleet_id) if message.fleet_id is not None else None,
                "branch_id": str(message.branch_id) if message.branch_id is not None else None,
                "payload": message.payload,
                "enqueued_at": message.enqueued_at.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def _decode_message(self, raw: str) -> QueueMessage:
        data = json.loads(raw)
        return QueueMessage(
            tenant_id=data["tenant_id"],
            task_id=uuid.UUID(data["task_id"]),
            mission_id=uuid.UUID(data["mission_id"]),
            fleet_id=uuid.UUID(data["fleet_id"]) if data.get("fleet_id") else None,
            branch_id=uuid.UUID(data["branch_id"]) if data.get("branch_id") else None,
            payload=dict(data.get("payload", {})),
            enqueued_at=datetime.fromisoformat(data["enqueued_at"]),
        )

    def _pending_key(self, tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:pending"

    def _processing_key(self, tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:processing"

    def _dead_letter_key(self, tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:dead_letter"

    def _lease_key(self, tenant_id: str, task_id: uuid.UUID) -> str:
        return f"ajenda:queue:{tenant_id}:lease:{task_id}"

    def _execute(self, command: list[str]) -> Any:
        with socket.create_connection((self._host, self._port), timeout=5.0) as conn:
            conn.settimeout(5.0)
            file_obj = conn.makefile("rwb")
            if self._password:
                self._write_command(file_obj, ["AUTH", self._password])
                auth_result = self._read_response(file_obj)
                if auth_result != "OK":
                    raise RedisProtocolError("AUTH failed")
            if self._db:
                self._write_command(file_obj, ["SELECT", str(self._db)])
                select_result = self._read_response(file_obj)
                if select_result != "OK":
                    raise RedisProtocolError("SELECT failed")
            self._write_command(file_obj, command)
            return self._read_response(file_obj)

    def _write_command(self, file_obj: Any, command: list[str]) -> None:
        encoded = f"*{len(command)}\r\n".encode()
        for part in command:
            item = part.encode("utf-8")
            encoded += f"${len(item)}\r\n".encode() + item + b"\r\n"
        file_obj.write(encoded)
        file_obj.flush()

    def _read_response(self, file_obj: Any) -> Any:
        prefix = file_obj.read(1)
        if not prefix:
            raise RedisProtocolError("empty response from Redis")
        if prefix == b"+":
            return self._read_line(file_obj)
        if prefix == b"-":
            raise RedisProtocolError(self._read_line(file_obj))
        if prefix == b":":
            return int(self._read_line(file_obj))
        if prefix == b"$":
            length = int(self._read_line(file_obj))
            if length == -1:
                return None
            data = file_obj.read(length)
            file_obj.read(2)
            return data.decode("utf-8")
        if prefix == b"*":
            length = int(self._read_line(file_obj))
            if length == -1:
                return None
            return [self._read_response(file_obj) for _ in range(length)]
        raise RedisProtocolError(f"unsupported Redis response prefix: {prefix!r}")

    def _read_line(self, file_obj: Any) -> str:
        line = file_obj.readline()
        if not line.endswith(b"\r\n"):
            raise RedisProtocolError("malformed Redis line response")
        decoded: str = line[:-2].decode("utf-8")
        return decoded
