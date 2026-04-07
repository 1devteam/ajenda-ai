from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult


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
                    "BRPOPLPUSH",
                    self._pending_key(tenant_id),
                    self._processing_key(tenant_id),
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
                    "failed_at": datetime.utcnow().isoformat() + "Z",
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
            deleted = self._execute(["DEL", self._lease_key(tenant_id, task_id)])
            if not isinstance(deleted, int):
                return QueueOperationResult(ok=False, reason="lease delete returned unexpected result")
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"release_lease failed: {exc}")

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        try:
            payload = self._find_processing_payload(tenant_id=tenant_id, task_id=task_id)
            if payload is None:
                return QueueOperationResult(ok=False, reason="task not found in processing queue")
            removed = self._execute(["LREM", self._processing_key(tenant_id), "1", payload])
            if not isinstance(removed, int) or removed < 1:
                return QueueOperationResult(ok=False, reason="processing payload was not removed")
            envelope = json.dumps(
                {
                    "task_id": str(task_id),
                    "reason": reason,
                    "moved_at": datetime.utcnow().isoformat() + "Z",
                    "payload": json.loads(payload),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            self._execute(["LPUSH", self._dead_letter_key(tenant_id), envelope])
            self._execute(["DEL", self._lease_key(tenant_id, task_id)])
            return QueueOperationResult(ok=True)
        except Exception as exc:
            return QueueOperationResult(ok=False, reason=f"move_to_dead_letter failed: {exc}")

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
        values = self._execute(["LRANGE", self._processing_key(tenant_id), "0", "-1"])
        if not isinstance(values, list):
            raise RedisProtocolError("LRANGE returned unexpected type")
        task_id_str = str(task_id)
        for item in values:
            if not isinstance(item, str):
                continue
            try:
                payload = json.loads(item)
            except json.JSONDecodeError:
                continue
            if payload.get("task_id") == task_id_str:
                return item
        return None

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
