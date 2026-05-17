from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.queue.base import QueueAdapter, QueueMessage, QueueOperationResult
from backend.services.runtime_maintainer import RuntimeMaintainer


class _QueryResult:
    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, Any]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows
        self.added: list[Any] = []
        self.flush_count = 0

    def execute(self, _stmt: Any) -> _QueryResult:
        return _QueryResult(self._rows)

    def add(self, value: Any) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1

    def refresh(self, _value: Any) -> None:
        return None


class _Queue(QueueAdapter):
    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []

    def ping(self) -> bool:
        return True

    def enqueue_task(self, message: QueueMessage) -> QueueOperationResult:
        self.messages.append(message)
        return QueueOperationResult(ok=True)

    def claim_task(self, *, tenant_id: str, worker_id: str) -> QueueMessage | None:
        return None

    def heartbeat(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def complete_task(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def fail_task(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
        reason: str,
    ) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def release_lease(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        worker_id: str,
    ) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def move_to_dead_letter(
        self,
        *,
        tenant_id: str,
        task_id: uuid.UUID,
        reason: str,
    ) -> QueueOperationResult:
        return QueueOperationResult(ok=True)


def _lease_task_pair(task_status: str) -> tuple[Any, Any]:
    task_id = uuid.uuid4()
    mission_id = uuid.uuid4()

    lease = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        task_id=task_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    task = SimpleNamespace(
        id=task_id,
        tenant_id="tenant-a",
        mission_id=mission_id,
        fleet_id=None,
        branch_id=None,
        status=task_status,
        metadata_json={"kind": "test"},
    )
    return lease, task


def test_runtime_recovery_expires_lease_and_routes_running_task_through_recovering() -> None:
    lease, task = _lease_task_pair(ExecutionTaskState.RUNNING.value)
    queue = _Queue()
    session = _Session([(lease, task)])

    summary = RuntimeMaintainer(session, queue, expiry_seconds=60).recover_expired_leases()

    assert summary.expired_lease_count == 1
    assert summary.requeued_task_count == 1
    assert lease.status == WorkerLeaseState.EXPIRED.value
    assert task.status == ExecutionTaskState.QUEUED.value
    assert len(queue.messages) == 1
    assert queue.messages[0].task_id == task.id


def test_runtime_recovery_requeues_claimed_task_without_recovering_intermediate() -> None:
    lease, task = _lease_task_pair(ExecutionTaskState.CLAIMED.value)
    queue = _Queue()
    session = _Session([(lease, task)])

    summary = RuntimeMaintainer(session, queue, expiry_seconds=60).recover_expired_leases()

    assert summary.expired_lease_count == 1
    assert summary.requeued_task_count == 1
    assert lease.status == WorkerLeaseState.EXPIRED.value
    assert task.status == ExecutionTaskState.QUEUED.value
    assert len(queue.messages) == 1
    assert queue.messages[0].task_id == task.id
