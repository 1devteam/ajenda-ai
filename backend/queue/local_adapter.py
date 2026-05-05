from __future__ import annotations

import threading
import uuid
from collections import deque

from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult


class LocalQueueAdapter(QueueAdapter):
    """Replaceable local adapter for explicit development/test use only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: deque[QueueMessage] = deque()
        self._claims: dict[tuple[str, uuid.UUID], tuple[str, QueueMessage]] = {}
        self._dead_letter: list[tuple[str, uuid.UUID, str]] = []

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

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        with self._lock:
            claim = self._claims.get((tenant_id, task_id))
            owner = claim[0] if claim is not None else None
            if owner != worker_id:
                return QueueOperationResult(ok=False, reason="worker does not own claim")
        return QueueOperationResult(ok=True)

    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return self.release_lease(tenant_id=tenant_id, task_id=task_id, worker_id=worker_id)

    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        return self.release_lease(tenant_id=tenant_id, task_id=task_id, worker_id=worker_id)

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
            self._dead_letter.append((tenant_id, task_id, reason))
            self._claims.pop((tenant_id, task_id), None)
            self._queue = deque(
                message
                for message in self._queue
                if not (message.tenant_id == tenant_id and message.task_id == task_id)
            )
        return QueueOperationResult(ok=True)
