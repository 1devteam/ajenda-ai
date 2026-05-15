from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from typing import cast

from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult


class LocalQueueAdapter(QueueAdapter):
    """Replaceable local adapter for explicit development/test use only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: deque[QueueMessage] = deque()
        self._claims: dict[tuple[str, uuid.UUID], tuple[str, QueueMessage]] = {}
        self._dead_letter: list[dict[str, object]] = []

    def ping(self) -> bool:
        return True

    def enqueue_task(self, message: QueueMessage) -> QueueOperationResult:
        with self._lock:
            self._queue.append(message)
        return QueueOperationResult(ok=True)

    def claim_task(self, *, tenant_id: str, worker_id: str) -> QueueMessage | None:
        with self._lock:
            for _ in range(len(self._queue)):
                message = self._queue.popleft()
                if message.tenant_id != tenant_id:
                    self._queue.append(message)
                    continue
                key = (tenant_id, message.task_id)
                if key in self._claims:
                    self._queue.append(message)
                    continue
                self._claims[key] = (worker_id, message)
                return message
        return None

    def claim_existing_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        with self._lock:
            key = (tenant_id, task_id)
            existing = self._claims.get(key)
            if existing is not None:
                owner = existing[0]
                if owner == worker_id:
                    return QueueOperationResult(ok=True)
                return QueueOperationResult(ok=False, reason="task already claimed by different worker")

            kept_queue: deque[QueueMessage] = deque()
            matched: QueueMessage | None = None
            while self._queue:
                message = self._queue.popleft()
                if matched is None and message.tenant_id == tenant_id and message.task_id == task_id:
                    matched = message
                else:
                    kept_queue.append(message)
            self._queue = kept_queue
            if matched is None:
                return QueueOperationResult(ok=False, reason="task not found in pending or processing queue")
            self._claims[key] = (worker_id, matched)
        return QueueOperationResult(ok=True)

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        with self._lock:
            claim = self._claims.get((tenant_id, task_id))
            owner = claim[0] if claim is not None else None
            if owner != worker_id:
                return QueueOperationResult(ok=False, reason="worker does not own claim")
        return QueueOperationResult(ok=True)

    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        with self._lock:
            key = (tenant_id, task_id)
            claim = self._claims.get(key)
            owner = claim[0] if claim is not None else None
            if owner != worker_id:
                return QueueOperationResult(ok=False, reason="worker does not own claim")
            self._claims.pop(key)
        return QueueOperationResult(ok=True)

    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        with self._lock:
            key = (tenant_id, task_id)
            claim = self._claims.get(key)
            owner = claim[0] if claim is not None else None
            if owner != worker_id:
                return QueueOperationResult(ok=False, reason="worker does not own claim")
            _, message = self._claims.pop(key)
            self._dead_letter.append(self._dead_letter_envelope(message=message, worker_id=worker_id, reason=reason))
        return QueueOperationResult(ok=True)

    def release_lease(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        with self._lock:
            key = (tenant_id, task_id)
            claim = self._claims.get(key)
            owner = claim[0] if claim is not None else None
            if owner != worker_id:
                return QueueOperationResult(ok=False, reason="worker does not own claim")
            _, message = self._claims.pop(key)
            self._queue.append(message)
        return QueueOperationResult(ok=True)

    def recover_task_for_retry(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        with self._lock:
            key = (tenant_id, task_id)
            claim = self._claims.pop(key, None)
            pending_matches: list[QueueMessage] = []
            kept_queue: deque[QueueMessage] = deque()

            while self._queue:
                message = self._queue.popleft()
                if message.tenant_id == tenant_id and message.task_id == task_id:
                    pending_matches.append(message)
                else:
                    kept_queue.append(message)

            if pending_matches:
                canonical_message = pending_matches[0]
            elif claim is not None:
                canonical_message = claim[1]
            else:
                self._queue = kept_queue
                return QueueOperationResult(ok=False, reason="task not found in processing or pending queue")

            kept_queue.append(canonical_message)
            self._queue = kept_queue
        return QueueOperationResult(ok=True)

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        with self._lock:
            claim = self._claims.pop((tenant_id, task_id), None)
            matched: QueueMessage | None = claim[1] if claim is not None else None
            kept_queue: deque[QueueMessage] = deque()
            while self._queue:
                message = self._queue.popleft()
                if matched is None and message.tenant_id == tenant_id and message.task_id == task_id:
                    matched = message
                    continue
                if not (message.tenant_id == tenant_id and message.task_id == task_id):
                    kept_queue.append(message)
            self._queue = kept_queue
            self._dead_letter.append(
                self._dead_letter_envelope(message=matched, tenant_id=tenant_id, task_id=task_id, reason=reason)
            )
        return QueueOperationResult(ok=True)

    def _dead_letter_envelope(
        self,
        *,
        reason: str,
        message: QueueMessage | None = None,
        tenant_id: str | None = None,
        task_id: uuid.UUID | None = None,
        worker_id: str | None = None,
    ) -> dict[str, object]:
        payload = (
            self._message_payload(message)
            if message is not None
            else {
                "tenant_id": tenant_id,
                "task_id": str(task_id) if task_id is not None else None,
                "source": "runtime_recovery_without_processing_payload",
            }
        )
        envelope: dict[str, object] = {
            "task_id": str(message.task_id if message is not None else task_id),
            "reason": reason,
            "failed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "payload": payload,
        }
        if worker_id is not None:
            envelope["worker_id"] = worker_id
        return envelope

    def _message_payload(self, message: QueueMessage) -> dict[str, object]:
        payload = json.loads(
            json.dumps(
                {
                    "tenant_id": message.tenant_id,
                    "task_id": str(message.task_id),
                    "mission_id": str(message.mission_id),
                    "fleet_id": str(message.fleet_id) if message.fleet_id is not None else None,
                    "branch_id": str(message.branch_id) if message.branch_id is not None else None,
                    "payload": message.payload,
                    "enqueued_at": message.enqueued_at.isoformat(),
                }
            )
        )
        return cast(dict[str, object], payload)
