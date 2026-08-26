from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.queue.adapters.redis_adapter import RedisProtocolError, RedisQueueAdapter
from backend.queue.base import QueueMessage, QueueOperationResult


class OwnerSafeRedisQueueAdapter(RedisQueueAdapter):
    """Redis queue adapter whose lease-sensitive mutations are owner-checked atomically."""

    _CLAIM_MOVED_TASK_SCRIPT = """
local processing_key = KEYS[1]
local pending_key = KEYS[2]
local lease_key = KEYS[3]
local raw = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = ARGV[3]

local owner = redis.call("GET", lease_key)
if owner ~= false and owner ~= worker_id then
    local removed = redis.call("LREM", processing_key, 1, raw)
    if removed > 0 then
        redis.call("RPUSH", pending_key, raw)
    end
    return {0, "task already claimed by different worker"}
end

redis.call("SET", lease_key, worker_id, "EX", ttl_seconds)
return {1, "ok"}
"""

    _CLAIM_EXISTING_TASK_OWNER_SCRIPT = """
local pending_key = KEYS[1]
local processing_key = KEYS[2]
local lease_key = KEYS[3]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local ttl_seconds = ARGV[3]

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
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
        redis.call("EXPIRE", lease_key, ttl_seconds)
        return {1, "ok"}
    end
end

local owner = redis.call("GET", lease_key)
if owner ~= false and owner ~= worker_id then
    return {0, "task already claimed by different worker"}
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

    _HEARTBEAT_OWNER_SCRIPT = """
local lease_key = KEYS[1]
local worker_id = ARGV[1]
local ttl_seconds = ARGV[2]

local owner = redis.call("GET", lease_key)
if owner == false then
    return {0, "lease owner missing"}
end
if owner ~= worker_id then
    return {0, "worker does not own claim"}
end
redis.call("EXPIRE", lease_key, ttl_seconds)
return {1, "ok"}
"""

    _COMPLETE_OWNER_SCRIPT = """
local processing_key = KEYS[1]
local lease_key = KEYS[2]
local task_id = ARGV[1]
local worker_id = ARGV[2]

local owner = redis.call("GET", lease_key)
if owner == false then
    return {0, "lease owner missing"}
end
if owner ~= worker_id then
    return {0, "worker does not own claim"}
end

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local processing_values = redis.call("LRANGE", processing_key, 0, -1)
for _, raw in ipairs(processing_values) do
    if payload_task_id(raw) == task_id then
        local removed = redis.call("LREM", processing_key, 1, raw)
        if removed < 1 then
            return {0, "processing payload was not removed"}
        end
        redis.call("DEL", lease_key)
        return {1, "ok"}
    end
end
return {0, "task not found in processing queue"}
"""

    _FAIL_OWNER_SCRIPT = """
local processing_key = KEYS[1]
local dead_letter_key = KEYS[2]
local lease_key = KEYS[3]
local task_id = ARGV[1]
local worker_id = ARGV[2]
local reason = ARGV[3]
local failed_at = ARGV[4]

local owner = redis.call("GET", lease_key)
if owner == false then
    return {0, "lease owner missing"}
end
if owner ~= worker_id then
    return {0, "worker does not own claim"}
end

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local processing_values = redis.call("LRANGE", processing_key, 0, -1)
for _, raw in ipairs(processing_values) do
    if payload_task_id(raw) == task_id then
        local removed = redis.call("LREM", processing_key, 1, raw)
        if removed < 1 then
            return {0, "processing payload was not removed"}
        end
        local ok, payload = pcall(cjson.decode, raw)
        if not ok or type(payload) ~= "table" then
            return {0, "processing payload is corrupt"}
        end
        local envelope = cjson.encode({
            task_id = task_id,
            worker_id = worker_id,
            reason = reason,
            failed_at = failed_at,
            payload = payload
        })
        redis.call("LPUSH", dead_letter_key, envelope)
        redis.call("DEL", lease_key)
        return {1, "ok"}
    end
end
return {0, "task not found in processing queue"}
"""

    _RELEASE_OWNER_SCRIPT = """
local processing_key = KEYS[1]
local pending_key = KEYS[2]
local lease_key = KEYS[3]
local task_id = ARGV[1]
local worker_id = ARGV[2]

local owner = redis.call("GET", lease_key)
if owner == false then
    return {0, "lease owner missing"}
end
if owner ~= worker_id then
    return {0, "worker does not own claim"}
end

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local processing_values = redis.call("LRANGE", processing_key, 0, -1)
for _, raw in ipairs(processing_values) do
    if payload_task_id(raw) == task_id then
        local removed = redis.call("LREM", processing_key, 1, raw)
        if removed < 1 then
            return {0, "processing payload was not removed"}
        end
        redis.call("RPUSH", pending_key, raw)
        redis.call("DEL", lease_key)
        return {1, "ok"}
    end
end
return {0, "task not found in processing queue"}
"""

    _RECOVER_OWNER_SCRIPT = """
local processing_key = KEYS[1]
local pending_key = KEYS[2]
local lease_key = KEYS[3]
local task_id = ARGV[1]
local worker_id = ARGV[2]

local owner = redis.call("GET", lease_key)
if owner ~= false and owner ~= worker_id then
    return {0, "worker does not own claim"}
end

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
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

    _DEAD_LETTER_UNOWNED_SCRIPT = """
local processing_key = KEYS[1]
local pending_key = KEYS[2]
local dead_letter_key = KEYS[3]
local lease_key = KEYS[4]
local task_id = ARGV[1]
local reason = ARGV[2]
local moved_at = ARGV[3]
local tenant_id = ARGV[4]

if redis.call("GET", lease_key) ~= false then
    return {0, "active worker owns claim"}
end

local function payload_task_id(raw)
    local ok, payload = pcall(cjson.decode, raw)
    if not ok or type(payload) ~= "table" or payload["task_id"] == nil then
        return nil
    end
    return tostring(payload["task_id"])
end

local envelope_payload = nil
local processing_values = redis.call("LRANGE", processing_key, 0, -1)
for _, raw in ipairs(processing_values) do
    if envelope_payload == nil and payload_task_id(raw) == task_id then
        local removed = redis.call("LREM", processing_key, 1, raw)
        if removed < 1 then
            return {0, "processing payload was not removed"}
        end
        local ok, payload = pcall(cjson.decode, raw)
        if not ok or type(payload) ~= "table" then
            return {0, "processing payload is corrupt"}
        end
        envelope_payload = payload
    end
end

if envelope_payload == nil then
    local pending_values = redis.call("LRANGE", pending_key, 0, -1)
    for _, raw in ipairs(pending_values) do
        if envelope_payload == nil and payload_task_id(raw) == task_id then
            local removed = redis.call("LREM", pending_key, 1, raw)
            if removed < 1 then
                return {0, "pending payload was not removed"}
            end
            local ok, payload = pcall(cjson.decode, raw)
            if not ok or type(payload) ~= "table" then
                return {0, "pending payload is corrupt"}
            end
            envelope_payload = payload
        end
    end
end

if envelope_payload == nil then
    envelope_payload = {
        tenant_id = tenant_id,
        task_id = task_id,
        source = "runtime_recovery_without_processing_payload"
    }
end

local envelope = cjson.encode({
    task_id = task_id,
    reason = reason,
    moved_at = moved_at,
    payload = envelope_payload
})
redis.call("LPUSH", dead_letter_key, envelope)
return {1, "ok"}
"""

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
            claim = self._execute(
                [
                    "EVAL",
                    self._CLAIM_MOVED_TASK_SCRIPT,
                    "3",
                    self._processing_key(tenant_id),
                    self._pending_key(tenant_id),
                    self._lease_key(tenant_id, message.task_id),
                    result,
                    worker_id,
                    str(self._heartbeat_ttl_seconds),
                ]
            )
            parsed = self._operation_result(claim, "claim")
            if not parsed.ok:
                raise RuntimeError(parsed.reason or "claim rejected")
            return message
        except Exception as exc:
            raise RuntimeError(f"claim_task failed: {exc}") from exc

    def claim_existing_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._CLAIM_EXISTING_TASK_OWNER_SCRIPT,
                    "3",
                    self._pending_key(tenant_id),
                    self._processing_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    worker_id,
                    str(self._heartbeat_ttl_seconds),
                ]
            )
            return self._operation_result(result, "claim")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"claim_existing_task failed: {exc}")

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._HEARTBEAT_OWNER_SCRIPT,
                    "1",
                    self._lease_key(tenant_id, task_id),
                    worker_id,
                    str(self._heartbeat_ttl_seconds),
                ]
            )
            return self._operation_result(result, "heartbeat")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"heartbeat failed: {exc}")

    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._COMPLETE_OWNER_SCRIPT,
                    "2",
                    self._processing_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    worker_id,
                ]
            )
            return self._operation_result(result, "complete")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"complete_task failed: {exc}")

    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._FAIL_OWNER_SCRIPT,
                    "3",
                    self._processing_key(tenant_id),
                    self._dead_letter_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    worker_id,
                    reason,
                    datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                ]
            )
            return self._operation_result(result, "fail")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"fail_task failed: {exc}")

    def release_lease(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._RELEASE_OWNER_SCRIPT,
                    "3",
                    self._processing_key(tenant_id),
                    self._pending_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    worker_id,
                ]
            )
            return self._operation_result(result, "release")
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
                    self._RECOVER_OWNER_SCRIPT,
                    "3",
                    self._processing_key(tenant_id),
                    self._pending_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    worker_id,
                ]
            )
            return self._operation_result(result, "recovery")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"recover_task_for_retry failed: {exc}")

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        """Dead-letter only work with no active Redis owner.

        Worker-owned failure uses fail_task(), which carries the worker identity.
        This method is reserved for unowned recovery/control-plane cleanup.
        """
        try:
            result = self._execute(
                [
                    "EVAL",
                    self._DEAD_LETTER_UNOWNED_SCRIPT,
                    "4",
                    self._processing_key(tenant_id),
                    self._pending_key(tenant_id),
                    self._dead_letter_key(tenant_id),
                    self._lease_key(tenant_id, task_id),
                    str(task_id),
                    reason,
                    datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    tenant_id,
                ]
            )
            return self._operation_result(result, "dead-letter")
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"move_to_dead_letter failed: {exc}")

    @staticmethod
    def _operation_result(result: object, operation: str) -> QueueOperationResult:
        if not isinstance(result, list) or len(result) != 2:
            return QueueOperationResult(ok=False, reason=f"{operation} script returned unexpected result")
        ok, reason = result
        if ok != 1:
            return QueueOperationResult(ok=False, reason=str(reason))
        return QueueOperationResult(ok=True)
