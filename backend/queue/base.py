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
    def move_to_dead_letter(self, *, tenant_id: str, task_id: uuid.UUID, reason: str) -> QueueOperationResult:
        raise NotImplementedError
