from __future__ import annotations

import uuid

from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult


class NatsQueueAdapter(QueueAdapter):
    """Stub NATS adapter — not yet implemented. Returns success for all operations."""

    def enqueue_task(self, message: QueueMessage) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def claim_task(self, *, tenant_id: str, worker_id: str) -> QueueMessage | None:
        return None

    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def release_lease(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        return QueueOperationResult(ok=True)
