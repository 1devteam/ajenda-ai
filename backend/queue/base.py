from __future__ import annotations

import abc
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class QueueMessage:
    tenant_id: str
    task_id: uuid.UUID
    mission_id: uuid.UUID
    fleet_id: uuid.UUID | None
    branch_id: uuid.UUID | None
    payload: dict[str, Any]
    enqueued_at: datetime


@dataclass(frozen=True, slots=True)
class QueuePayloadInspection:
    tenant_id: str
    raw: Any
    message: QueueMessage | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueueDeadLetterEntry:
    tenant_id: str
    task_id: uuid.UUID | None
    raw: Any
    payload: dict[str, Any] | None = None
    reason: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueueOperationResult:
    ok: bool
    reason: str | None = None


class QueueAdapter(abc.ABC):
    @abc.abstractmethod
    def ping(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def enqueue_task(self, message: QueueMessage) -> QueueOperationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def claim_task(self, *, tenant_id: str, worker_id: str) -> QueueMessage | None:
        raise NotImplementedError

    @abc.abstractmethod
    def claim_existing_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        """Move an existing queued payload for task_id into processing for worker_id.

        Must fail closed when no queued/processing payload exists and must not
        synthesize replacement payloads from database state. Already-processing
        payloads owned by worker_id should be treated idempotently.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def heartbeat(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def complete_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def fail_task(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str, reason: str) -> QueueOperationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def release_lease(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def recover_task_for_retry(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        """Converge recoverable expired work to one pending payload.

        Implementations must fail closed when no pending or processing payload
        exists. They must not synthesize replacement work from database state.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        """Dead-letter work only when no active queue owner must be overridden."""
        raise NotImplementedError

    def move_owned_to_dead_letter(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
        reason: str,
    ) -> QueueOperationResult:
        """Dead-letter expired work while proving the last recorded queue owner.

        Queue backends that cannot atomically verify the supplied worker owner
        must fail closed rather than delegate to the ownerless dead-letter path.
        """
        return QueueOperationResult(ok=False, reason="owner-aware dead-letter not supported")

    @abc.abstractmethod
    def list_processing(self, *, tenant_id: str) -> list[QueuePayloadInspection]:
        raise NotImplementedError

    @abc.abstractmethod
    def list_dead_letter(self, *, tenant_id: str) -> list[QueueDeadLetterEntry]:
        raise NotImplementedError

    @abc.abstractmethod
    def retry_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID) -> QueueOperationResult:
        raise NotImplementedError

    @abc.abstractmethod
    def pending_depth(self, *, tenant_id: str) -> int:
        """Return the number of pending queue payloads for a tenant."""
        raise NotImplementedError
