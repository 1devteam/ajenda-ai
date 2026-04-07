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
        self._claims: dict[tuple[str, uuid.UUID], str] = {}
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
                self._claims[key] = worker_id
                return message
        return None

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        with self._lock:
            owner = self._claims.get((tenant_id, task_id))
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
            owner = self._claims.get(key)
            if owner != worker_id:
                return QueueOperationResult(ok=False, reason="worker does not own claim")
            del self._claims[key]
        return QueueOperationResult(ok=True)

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        with self._lock:
            self._dead_letter.append((tenant_id, task_id, reason))
            self._claims.pop((tenant_id, task_id), None)
        return QueueOperationResult(ok=True)
