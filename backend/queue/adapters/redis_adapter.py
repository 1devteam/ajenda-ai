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
    """Indexed, tenant-scoped Redis queue with atomic owner-safe transitions.

    Pending order is a sorted set while payloads and processing/dead-letter
    state are hashes keyed by task id. Task-specific lifecycle operations are
    O(1) hash lookups plus O(log n) sorted-set updates and never scan a full
    tenant queue.

    The first operation for a tenant atomically migrates the legacy list
    representation. Migration fails closed on malformed or duplicate task
    identities and on legacy writes that appear after migration.
    """

    _MIGRATE_LEGACY_SCRIPT = """
local legacy_pending = KEYS[1]
local legacy_processing = KEYS[2]
local legacy_dead = KEYS[3]
local pending_order = KEYS[4]
local pending_payloads = KEYS[5]
local processing_payloads = KEYS[6]
local dead_order = KEYS[7]
local dead_payloads = KEYS[8]
local sequence_key = KEYS[9]
local schema_key = KEYS[10]
local expected_tenant_id = ARGV[1]

local function key_type(key)
    local value = redis.call("TYPE", key)
    if type(value) == "table" then return value["ok"] end
    return value
end

local function legacy_is_empty(key)
    local kind = key_type(key)
    if kind == "none" then return true end
    if kind ~= "list" then return false end
    return redis.call("LLEN", key) == 0
end

if redis.call("EXISTS", schema_key) == 1 then
    if not legacy_is_empty(legacy_pending)
        or not legacy_is_empty(legacy_processing)
        or not legacy_is_empty(legacy_dead) then
        return {0, "legacy queue received data after indexed migration"}
    end
    return {1, "ready"}
end

for _, key in ipairs({legacy_pending, legacy_processing, legacy_dead}) do
    local kind = key_type(key)
    if kind ~= "none" and kind ~= "list" then
        return {0, "legacy queue key has unexpected type"}
    end
end
for _, key in ipairs({pending_order, dead_order}) do
    local kind = key_type(key)
    if kind ~= "none" and kind ~= "zset" then
        return {0, "indexed order key has unexpected type"}
    end
end
for _, key in ipairs({pending_payloads, processing_payloads, dead_payloads}) do
    local kind = key_type(key)
    if kind ~= "none" and kind ~= "hash" then
        return {0, "indexed payload key has unexpected type"}
    end
end

if redis.call("EXISTS", pending_order) == 1
    or redis.call("EXISTS", pending_payloads) == 1
    or redis.call("EXISTS", processing_payloads) == 1
    or redis.call("EXISTS", dead_order) == 1
    or redis.call("EXISTS", dead_payloads) == 1 then
    return {0, "partial indexed queue exists without schema marker"}
end

local pending_rows = {}
local processing_rows = {}
local dead_rows = {}
local seen_live = {}
local seen_dead = {}

for _, raw in ipairs(redis.call("LRANGE", legacy_pending, 0, -1)) do
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
        return {0, "legacy pending payload is corrupt"}
    end
    local task_id = tostring(payload["task_id"])
    if payload["tenant_id"] == nil or tostring(payload["tenant_id"]) ~= expected_tenant_id then
        return {0, "legacy pending payload tenant mismatch"}
    end
    if seen_live[task_id] then
        return {0, "legacy queue contains duplicate live task"}
    end
    seen_live[task_id] = true
    table.insert(pending_rows, {task_id, raw})
end
for _, raw in ipairs(redis.call("LRANGE", legacy_processing, 0, -1)) do
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
        return {0, "legacy processing payload is corrupt"}
    end
    local task_id = tostring(payload["task_id"])
    if payload["tenant_id"] == nil or tostring(payload["tenant_id"]) ~= expected_tenant_id then
        return {0, "legacy processing payload tenant mismatch"}
    end
    if seen_live[task_id] then
        return {0, "legacy queue contains duplicate live task"}
    end
    seen_live[task_id] = true
    table.insert(processing_rows, {task_id, raw})
end
for _, raw in ipairs(redis.call("LRANGE", legacy_dead, 0, -1)) do
    local ok, envelope = pcall(cjson.decode, raw)
    if not ok or type(envelope) ~= "table" or envelope["task_id"] == nil then
        return {0, "legacy dead-letter payload is corrupt"}
    end
    local task_id = tostring(envelope["task_id"])
    local payload = envelope["payload"]
    if type(payload) ~= "table"
        or payload["tenant_id"] == nil
        or tostring(payload["tenant_id"]) ~= expected_tenant_id then
        return {0, "legacy dead-letter payload tenant mismatch"}
    end
    if seen_dead[task_id] then
        return {0, "legacy queue contains duplicate dead-letter task"}
    end
    seen_dead[task_id] = true
    table.insert(dead_rows, {task_id, raw})
end

for _, row in ipairs(pending_rows) do
    local score = redis.call("INCR", sequence_key)
    redis.call("HSET", pending_payloads, row[1], row[2])
    redis.call("ZADD", pending_order, score, row[1])
end
for _, row in ipairs(processing_rows) do
    redis.call("HSET", processing_payloads, row[1], row[2])
end
for _, row in ipairs(dead_rows) do
    local score = redis.call("INCR", sequence_key)
    redis.call("HSET", dead_payloads, row[1], row[2])
    redis.call("ZADD", dead_order, score, row[1])
end
redis.call("DEL", legacy_pending)
redis.call("DEL", legacy_processing)
redis.call("DEL", legacy_dead)
redis.call("SET", schema_key, "indexed-v2")
return {1, "migrated"}
"""

    _ENQUEUE_SCRIPT = """
local pending_order = KEYS[1]
local pending_payloads = KEYS[2]
local processing_payloads = KEYS[3]
local sequence_key = KEYS[4]
local task_id = ARGV[1]
local payload = ARGV[2]
if redis.call("HEXISTS", processing_payloads, task_id) == 1 then
    return {0, "task already processing"}
end
if redis.call("HEXISTS", pending_payloads, task_id) == 1 then
    return {0, "task already pending"}
end
local score = redis.call("INCR", sequence_key)
redis.call("HSET", pending_payloads, task_id, payload)
redis.call("ZADD", pending_order, score, task_id)
return {1, "published"}
"""

    _IDEMPOTENT_ENQUEUE_SCRIPT = """
local pending_order = KEYS[1]
local pending_payloads = KEYS[2]
local processing_payloads = KEYS[3]
local sequence_key = KEYS[4]
local idempotency_key = KEYS[5]
local task_id = ARGV[1]
local payload = ARGV[2]
if redis.call("EXISTS", idempotency_key) == 1 then
    return {1, "already_published"}
end
if redis.call("HEXISTS", processing_payloads, task_id) == 1 then
    return {0, "task already processing"}
end
if redis.call("HEXISTS", pending_payloads, task_id) == 1 then
    return {0, "task already pending"}
end
local score = redis.call("INCR", sequence_key)
redis.call("HSET", pending_payloads, task_id, payload)
redis.call("ZADD", pending_order, score, task_id)
redis.call("SET", idempotency_key, "published")
return {1, "published"}
"""

    _CANCEL_PENDING_TASK_SCRIPT = """
local pending_order = KEYS[1]
local pending_payloads = KEYS[2]
local processing_payloads = KEYS[3]
local task_id = ARGV[1]
if redis.call("HEXISTS", processing_payloads, task_id) == 1 then
    return {0, "task is processing with an active owner"}
end
redis.call("ZREM", pending_order, task_id)
redis.call("HDEL", pending_payloads, task_id)
return {1, "cancelled"}
"""

    _CLAIM_NEXT_TASK_SCRIPT = """
local pending_order = KEYS[1]
local pending_payloads = KEYS[2]
local processing_payloads = KEYS[3]
local lease_prefix = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = ARGV[3]
local first = redis.call("ZRANGE", pending_order, 0, 0)
if #first == 0 then return {0, "empty"} end
local task_id = first[1]
local payload = redis.call("HGET", pending_payloads, task_id)
if payload == false then return {0, "pending index is missing payload"} end
local lease_key = lease_prefix .. task_id
if redis.call("EXISTS", lease_key) == 1 then
    return {0, "task already claimed by different worker"}
end
redis.call("ZREM", pending_order, task_id)
redis.call("HDEL", pending_payloads, task_id)
redis.call("HSET", processing_payloads, task_id, payload)
redis.call("SET", lease_key, worker_id, "EX", ttl_seconds)
return {1, payload}
"""

    _CLAIM_EXISTING_TASK_SCRIPT = """
local pending_order = KEYS[1]
local pending_payloads = KEYS[2]
local processing_payloads = KEYS[3]
local lease_key = KEYS[4]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = ARGV[3]
local processing_payload = redis.call("HGET", processing_payloads, task_id)
if processing_payload ~= false then
    local owner = redis.call("GET", lease_key)
    if owner == false then return {0, "processing payload has no worker owner"} end
    if owner ~= worker_id then return {0, "task already claimed by different worker"} end
    redis.call("EXPIRE", lease_key, ttl_seconds)
    return {1, "ok"}
end
local pending_payload = redis.call("HGET", pending_payloads, task_id)
if pending_payload == false then
    return {0, "task not found in pending or processing queue"}
end
local owner = redis.call("GET", lease_key)
if owner ~= false and owner ~= worker_id then
    return {0, "task already claimed by different worker"}
end
redis.call("ZREM", pending_order, task_id)
redis.call("HDEL", pending_payloads, task_id)
redis.call("HSET", processing_payloads, task_id, pending_payload)
redis.call("SET", lease_key, worker_id, "EX", ttl_seconds)
return {1, "ok"}
"""

    _HEARTBEAT_OWNER_SCRIPT = """
local lease_key = KEYS[1]
local worker_id = ARGV[1]
local ttl_seconds = ARGV[2]
local owner = redis.call("GET", lease_key)
if owner == false then return {0, "lease owner missing"} end
if owner ~= worker_id then return {0, "worker does not own claim"} end
redis.call("EXPIRE", lease_key, ttl_seconds)
return {1, "ok"}
"""

    _COMPLETE_OWNER_SCRIPT = """
local processing_payloads = KEYS[1]
local lease_key = KEYS[2]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local owner = redis.call("GET", lease_key)
if owner == false then return {0, "lease owner missing"} end
if owner ~= worker_id then return {0, "worker does not own claim"} end
if redis.call("HEXISTS", processing_payloads, task_id) == 0 then
    return {0, "task not found in processing queue"}
end
redis.call("HDEL", processing_payloads, task_id)
redis.call("DEL", lease_key)
return {1, "ok"}
"""

    _FAIL_OWNER_SCRIPT = """
local processing_payloads = KEYS[1]
local dead_order = KEYS[2]
local dead_payloads = KEYS[3]
local sequence_key = KEYS[4]
local lease_key = KEYS[5]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local reason = ARGV[3]
local failed_at = ARGV[4]
local owner = redis.call("GET", lease_key)
if owner == false then return {0, "lease owner missing"} end
if owner ~= worker_id then return {0, "worker does not own claim"} end
local raw = redis.call("HGET", processing_payloads, task_id)
if raw == false then return {0, "task not found in processing queue"} end
local ok, payload = pcall(cjson.decode, raw)
if not ok or type(payload) ~= "table" then
    return {0, "processing payload is corrupt"}
end
local envelope = cjson.encode({
    task_id = task_id, worker_id = worker_id, reason = reason,
    failed_at = failed_at, payload = payload
})
local score = redis.call("INCR", sequence_key)
redis.call("HDEL", processing_payloads, task_id)
redis.call("HSET", dead_payloads, task_id, envelope)
redis.call("ZADD", dead_order, score, task_id)
redis.call("DEL", lease_key)
return {1, "ok"}
"""

    _RELEASE_OWNER_SCRIPT = """
local processing_payloads = KEYS[1]
local pending_order = KEYS[2]
local pending_payloads = KEYS[3]
local sequence_key = KEYS[4]
local lease_key = KEYS[5]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local owner = redis.call("GET", lease_key)
if owner == false then return {0, "lease owner missing"} end
if owner ~= worker_id then return {0, "worker does not own claim"} end
local payload = redis.call("HGET", processing_payloads, task_id)
if payload == false then return {0, "task not found in processing queue"} end
local score = redis.call("INCR", sequence_key)
redis.call("HDEL", processing_payloads, task_id)
redis.call("HSET", pending_payloads, task_id, payload)
redis.call("ZADD", pending_order, score, task_id)
redis.call("DEL", lease_key)
return {1, "ok"}
"""

    _RECOVER_OWNER_SCRIPT = """
local processing_payloads = KEYS[1]
local pending_order = KEYS[2]
local pending_payloads = KEYS[3]
local sequence_key = KEYS[4]
local lease_key = KEYS[5]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local owner = redis.call("GET", lease_key)
if owner ~= false and owner ~= worker_id then
    return {0, "worker does not own claim"}
end
local processing_payload = redis.call("HGET", processing_payloads, task_id)
local pending_payload = redis.call("HGET", pending_payloads, task_id)
if processing_payload ~= false and pending_payload ~= false then
    return {0, "task exists in both pending and processing queues"}
end
local payload = processing_payload
if payload == false then payload = pending_payload end
if payload == false then
    return {0, "task not found in processing or pending queue"}
end
local score = redis.call("INCR", sequence_key)
redis.call("HDEL", processing_payloads, task_id)
redis.call("HSET", pending_payloads, task_id, payload)
redis.call("ZADD", pending_order, score, task_id)
redis.call("DEL", lease_key)
return {1, "ok"}
"""

    _DEAD_LETTER_SCRIPT = """
local processing_payloads = KEYS[1]
local pending_order = KEYS[2]
local pending_payloads = KEYS[3]
local dead_order = KEYS[4]
local dead_payloads = KEYS[5]
local sequence_key = KEYS[6]
local lease_key = KEYS[7]
local task_id = ARGV[1]
local expected_owner = ARGV[2]
local reason = ARGV[3]
local moved_at = ARGV[4]
local tenant_id = ARGV[5]
local owner = redis.call("GET", lease_key)
if expected_owner == "" then
    if owner ~= false then return {0, "active worker owns claim"} end
elseif owner ~= false and owner ~= expected_owner then
    return {0, "worker does not own claim"}
end
local processing_payload = redis.call("HGET", processing_payloads, task_id)
local pending_payload = redis.call("HGET", pending_payloads, task_id)
if processing_payload ~= false and pending_payload ~= false then
    return {0, "task exists in both pending and processing queues"}
end
local raw = processing_payload
if raw == false then raw = pending_payload end
local payload = nil
if raw ~= false then
    local ok, decoded = pcall(cjson.decode, raw)
    if not ok or type(decoded) ~= "table" then
        return {0, "queue payload is corrupt"}
    end
    payload = decoded
else
    payload = {
        tenant_id = tenant_id, task_id = task_id,
        source = "runtime_recovery_without_processing_payload"
    }
end
local envelope = {
    task_id = task_id, reason = reason, moved_at = moved_at, payload = payload
}
if expected_owner ~= "" then envelope["worker_id"] = expected_owner end
local score = redis.call("INCR", sequence_key)
redis.call("HDEL", processing_payloads, task_id)
redis.call("HDEL", pending_payloads, task_id)
redis.call("ZREM", pending_order, task_id)
redis.call("HSET", dead_payloads, task_id, cjson.encode(envelope))
redis.call("ZADD", dead_order, score, task_id)
redis.call("DEL", lease_key)
return {1, "ok"}
"""

    _RETRY_DEAD_LETTER_SCRIPT = """
local pending_order = KEYS[1]
local pending_payloads = KEYS[2]
local processing_payloads = KEYS[3]
local dead_order = KEYS[4]
local dead_payloads = KEYS[5]
local sequence_key = KEYS[6]
local tenant_id = ARGV[1]
local task_id = ARGV[2]
if redis.call("HEXISTS", pending_payloads, task_id) == 1 then
    return {0, "task already pending"}
end
if redis.call("HEXISTS", processing_payloads, task_id) == 1 then
    return {0, "task already processing"}
end
local raw = redis.call("HGET", dead_payloads, task_id)
if raw == false then return {0, "dead-letter entry not found"} end
local envelope_ok, envelope = pcall(cjson.decode, raw)
if not envelope_ok or type(envelope) ~= "table" then
    return {0, "dead-letter payload is corrupt: invalid envelope"}
end
local payload = envelope["payload"]
if type(payload) ~= "table" then
    return {0, "dead-letter payload is corrupt: payload is not an object"}
end
if payload["tenant_id"] == nil or tostring(payload["tenant_id"]) ~= tenant_id then
    return {0, "dead-letter payload is corrupt: tenant_id mismatch"}
end
if payload["task_id"] == nil or tostring(payload["task_id"]) ~= task_id then
    return {0, "dead-letter payload is corrupt: task_id mismatch"}
end
if payload["mission_id"] == nil then
    return {0, "dead-letter payload is corrupt: missing mission_id"}
end
if payload["payload"] == nil or type(payload["payload"]) ~= "table" then
    return {0, "dead-letter payload is corrupt: missing payload"}
end
if payload["enqueued_at"] == nil then
    return {0, "dead-letter payload is corrupt: missing enqueued_at"}
end
local score = redis.call("INCR", sequence_key)
redis.call("HDEL", dead_payloads, task_id)
redis.call("ZREM", dead_order, task_id)
redis.call("HSET", pending_payloads, task_id, cjson.encode(payload))
redis.call("ZADD", pending_order, score, task_id)
return {1, "ok"}
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
            self._ensure_queue_schema(message.tenant_id)
            result = self._execute(
                [
                    "EVAL",
                    self._ENQUEUE_SCRIPT,
                    "4",
                    self._pending_key(message.tenant_id),
                    self._pending_payloads_key(message.tenant_id),
                    self._processing_key(message.tenant_id),
                    self._sequence_key(message.tenant_id),
                    str(message.task_id),
                    self._encode_message(message),
                ]
            )
            return self._operation_result(result, "enqueue")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"enqueue failed: {exc}")

    def enqueue_task_idempotent(
        self,
        message: QueueMessage,
        *,
        idempotency_key: str,
    ) -> QueueOperationResult:
        try:
            self._ensure_queue_schema(message.tenant_id)
            result = self._execute(
                [
                    "EVAL",
                    self._IDEMPOTENT_ENQUEUE_SCRIPT,
                    "5",
                    self._pending_key(message.tenant_id),
                    self._pending_payloads_key(message.tenant_id),
                    self._processing_key(message.tenant_id),
                    self._sequence_key(message.tenant_id),
                    self._dispatch_key(message.tenant_id, idempotency_key),
                    str(message.task_id),
                    self._encode_message(message),
                ]
            )
            return self._operation_result(result, "idempotent enqueue")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"idempotent enqueue failed: {exc}")

    def cancel_task(self, *, tenant_id: str, task_id: uuid.UUID) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._CANCEL_PENDING_TASK_SCRIPT,
            keys=[
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._processing_key(tenant_id),
            ],
            args=[str(task_id)],
            operation="cancel",
        )

    def claim_task(self, *, tenant_id: str, worker_id: str) -> QueueMessage | None:
        try:
            self._ensure_queue_schema(tenant_id)
            result = self._execute(
                [
                    "EVAL",
                    self._CLAIM_NEXT_TASK_SCRIPT,
                    "3",
                    self._pending_key(tenant_id),
                    self._pending_payloads_key(tenant_id),
                    self._processing_key(tenant_id),
                    self._lease_prefix(tenant_id),
                    worker_id,
                    str(self._heartbeat_ttl_seconds),
                ]
            )
            if not isinstance(result, list) or len(result) != 2:
                raise RedisProtocolError("claim script returned unexpected result")
            ok, value = result
            if ok == 0 and value == "empty":
                return None
            if ok != 1 or not isinstance(value, str):
                raise RedisProtocolError(str(value))
            return self._decode_message(value)
        except Exception as exc:
            raise RuntimeError(f"claim_task failed: {exc}") from exc

    def claim_existing_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._CLAIM_EXISTING_TASK_SCRIPT,
            keys=[
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._processing_key(tenant_id),
                self._lease_key(tenant_id, task_id),
            ],
            args=[str(task_id), worker_id, str(self._heartbeat_ttl_seconds)],
            operation="claim",
        )

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._HEARTBEAT_OWNER_SCRIPT,
            keys=[self._lease_key(tenant_id, task_id)],
            args=[worker_id, str(self._heartbeat_ttl_seconds)],
            operation="heartbeat",
        )

    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._COMPLETE_OWNER_SCRIPT,
            keys=[self._processing_key(tenant_id), self._lease_key(tenant_id, task_id)],
            args=[str(task_id), worker_id],
            operation="complete",
        )

    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._FAIL_OWNER_SCRIPT,
            keys=[
                self._processing_key(tenant_id),
                self._dead_letter_key(tenant_id),
                self._dead_letter_payloads_key(tenant_id),
                self._sequence_key(tenant_id),
                self._lease_key(tenant_id, task_id),
            ],
            args=[
                str(task_id),
                worker_id,
                reason,
                datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            ],
            operation="fail",
        )

    def release_lease(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._RELEASE_OWNER_SCRIPT,
            keys=[
                self._processing_key(tenant_id),
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._sequence_key(tenant_id),
                self._lease_key(tenant_id, task_id),
            ],
            args=[str(task_id), worker_id],
            operation="release",
        )

    def recover_task_for_retry(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._RECOVER_OWNER_SCRIPT,
            keys=[
                self._processing_key(tenant_id),
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._sequence_key(tenant_id),
                self._lease_key(tenant_id, task_id),
            ],
            args=[str(task_id), worker_id],
            operation="recovery",
        )

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        return self._move_to_dead_letter(tenant_id=tenant_id, task_id=task_id, worker_id=None, reason=reason)

    def move_owned_to_dead_letter(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
        reason: str,
    ) -> QueueOperationResult:
        return self._move_to_dead_letter(
            tenant_id=tenant_id,
            task_id=task_id,
            worker_id=worker_id,
            reason=reason,
        )

    def list_processing(self, *, tenant_id: str) -> list[QueuePayloadInspection]:
        try:
            self._ensure_queue_schema(tenant_id)
            inspections: list[QueuePayloadInspection] = []
            for raw in self._hash_values(self._processing_key(tenant_id)):
                try:
                    message = self._decode_message(raw)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    inspections.append(
                        QueuePayloadInspection(
                            tenant_id=tenant_id,
                            raw=raw,
                            error=f"processing payload is corrupt: {exc}",
                        )
                    )
                    continue
                error = "processing payload tenant mismatch" if message.tenant_id != tenant_id else None
                inspections.append(QueuePayloadInspection(tenant_id=tenant_id, raw=raw, message=message, error=error))
            return inspections
        except Exception as exc:
            raise RuntimeError(f"list_processing failed: {exc}") from exc

    def list_dead_letter(self, *, tenant_id: str) -> list[QueueDeadLetterEntry]:
        try:
            self._ensure_queue_schema(tenant_id)
            entries: list[QueueDeadLetterEntry] = []
            for raw in self._hash_values(self._dead_letter_payloads_key(tenant_id)):
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
                if not isinstance(payload, dict) or payload.get("tenant_id") != tenant_id:
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
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._RETRY_DEAD_LETTER_SCRIPT,
            keys=[
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._processing_key(tenant_id),
                self._dead_letter_key(tenant_id),
                self._dead_letter_payloads_key(tenant_id),
                self._sequence_key(tenant_id),
            ],
            args=[tenant_id, str(task_id)],
            operation="retry",
        )

    def pending_depth(self, *, tenant_id: str) -> int:
        try:
            self._ensure_queue_schema(tenant_id)
            result = self._execute(["ZCARD", self._pending_key(tenant_id)])
        except Exception:
            return 0
        return int(result) if isinstance(result, int) else 0

    def _move_to_dead_letter(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str | None,
        reason: str,
    ) -> QueueOperationResult:
        return self._run_operation(
            tenant_id=tenant_id,
            script=self._DEAD_LETTER_SCRIPT,
            keys=[
                self._processing_key(tenant_id),
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._dead_letter_key(tenant_id),
                self._dead_letter_payloads_key(tenant_id),
                self._sequence_key(tenant_id),
                self._lease_key(tenant_id, task_id),
            ],
            args=[
                str(task_id),
                worker_id or "",
                reason,
                datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                tenant_id,
            ],
            operation="owner dead-letter" if worker_id else "dead-letter",
        )

    def _run_operation(
        self,
        *,
        tenant_id: str,
        script: str,
        keys: list[str],
        args: list[str],
        operation: str,
    ) -> QueueOperationResult:
        try:
            self._ensure_queue_schema(tenant_id)
            result = self._execute(["EVAL", script, str(len(keys)), *keys, *args])
            return self._operation_result(result, operation)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"{operation} failed: {exc}")

    def _ensure_queue_schema(self, tenant_id: str) -> None:
        result = self._execute(
            [
                "EVAL",
                self._MIGRATE_LEGACY_SCRIPT,
                "10",
                self._legacy_pending_key(tenant_id),
                self._legacy_processing_key(tenant_id),
                self._legacy_dead_letter_key(tenant_id),
                self._pending_key(tenant_id),
                self._pending_payloads_key(tenant_id),
                self._processing_key(tenant_id),
                self._dead_letter_key(tenant_id),
                self._dead_letter_payloads_key(tenant_id),
                self._sequence_key(tenant_id),
                self._schema_key(tenant_id),
                tenant_id,
            ]
        )
        parsed = self._operation_result(result, "queue schema migration")
        if not parsed.ok:
            raise RedisProtocolError(parsed.reason or "queue schema migration failed")

    @staticmethod
    def _operation_result(result: object, operation: str) -> QueueOperationResult:
        if not isinstance(result, list) or len(result) != 2:
            return QueueOperationResult(ok=False, reason=f"{operation} script returned unexpected result")
        ok, reason = result
        if ok != 1:
            return QueueOperationResult(ok=False, reason=str(reason))
        return QueueOperationResult(ok=True)

    def _hash_values(self, key: str) -> list[str]:
        values = self._execute(["HVALS", key])
        if not isinstance(values, list):
            raise RedisProtocolError("HVALS returned unexpected type")
        return [item for item in values if isinstance(item, str)]

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

    @staticmethod
    def _legacy_pending_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:pending"

    @staticmethod
    def _legacy_processing_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:processing"

    @staticmethod
    def _legacy_dead_letter_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:dead_letter"

    @staticmethod
    def _pending_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:pending-order"

    @staticmethod
    def _pending_payloads_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:pending-payloads"

    @staticmethod
    def _processing_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:processing-payloads"

    @staticmethod
    def _dead_letter_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:dead-letter-order"

    @staticmethod
    def _dead_letter_payloads_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:dead-letter-payloads"

    @staticmethod
    def _sequence_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:sequence"

    @staticmethod
    def _schema_key(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:v2:schema"

    @staticmethod
    def _dispatch_key(tenant_id: str, idempotency_key: str) -> str:
        return f"ajenda:queue:{tenant_id}:dispatch:{idempotency_key}"

    @staticmethod
    def _lease_prefix(tenant_id: str) -> str:
        return f"ajenda:queue:{tenant_id}:lease:"

    def _lease_key(self, tenant_id: str, task_id: uuid.UUID) -> str:
        return f"{self._lease_prefix(tenant_id)}{task_id}"

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
