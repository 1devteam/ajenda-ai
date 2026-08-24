from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.domain.execution_task import ExecutionTask
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueOperationResult
from backend.services.operations_service import OperationsService
from backend.services.runtime_maintainer import RecoverySummary, RuntimeMaintainer


class _Session:
    def __init__(self) -> None:
        self.flush_count = 0
        self.commit_count = 0

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1


class _Audit:
    def __init__(self) -> None:
        self.events = []

    def append(self, event) -> None:
        self.events.append(event)


class _Maintainer:
    def recover_expired_leases(self) -> RecoverySummary:
        return RecoverySummary(
            expired_lease_count=3,
            requeued_task_count=2,
            dead_lettered_count=1,
            mismatched_state_count=4,
        )


def test_manual_global_recovery_records_human_trigger_identity() -> None:
    service = object.__new__(OperationsService)
    service._session = _Session()
    service._audit = _Audit()
    service._maintainer = _Maintainer()

    summary = service.trigger_recovery(
        actor="user:admin-1",
        actor_tenant_id="admin-home-tenant",
    )

    assert summary.expired_lease_count == 3
    assert [event.action for event in service._audit.events] == [
        "global_recovery_requested",
        "global_recovery_completed",
    ]
    assert all(event.actor == "user:admin-1" for event in service._audit.events)
    assert service._audit.events[0].payload_json["trigger_source"] == "manual_api"
    assert service._audit.events[1].payload_json["mismatched_state_count"] == 4
    assert service._session.commit_count == 2


class _Rows:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _RecoverySession(_Session):
    def __init__(self, lease: WorkerLease, task: ExecutionTask) -> None:
        super().__init__()
        self._lease = lease
        self._task = task
        self.rollback_count = 0

    def execute(self, _statement) -> _Rows:
        return _Rows([(self._lease, self._task)])

    def scalars(self, _statement) -> _Rows:
        return _Rows([])

    def rollback(self) -> None:
        self.rollback_count += 1


class _Queue:
    def recover_task_for_retry(self, **_kwargs) -> QueueOperationResult:
        return QueueOperationResult(ok=True)

    def list_processing(self, *, tenant_id: str):
        return []


def test_automated_recovery_retains_runtime_maintainer_actor_identity() -> None:
    task_id = uuid.uuid4()
    task = ExecutionTask(
        id=task_id,
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        title="recover automatically",
        description="prove system attribution",
        status="running",
        retry_count=0,
        metadata_json={},
    )
    lease = WorkerLease(
        id=uuid.uuid4(),
        tenant_id="tenant-a",
        task_id=task_id,
        status="active",
        holder_identity="worker-1",
        heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
        metadata_json={},
    )
    session = _RecoverySession(lease, task)
    maintainer = RuntimeMaintainer(session, _Queue())
    audit = _Audit()
    maintainer._audit = audit

    summary = maintainer.recover_expired_leases()

    assert summary.requeued_task_count == 1
    assert [event.action for event in audit.events] == ["lease_expired_task_requeued"]
    assert audit.events[0].actor == "runtime_maintainer"
