from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueMessage
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.runtime_maintainer import RuntimeMaintainer
from backend.services.worker_runtime_service import WorkerRuntimeService

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class RunningTaskFixture:
    tenant_id: str
    task_id: uuid.UUID
    lease_id: uuid.UUID
    worker_id: str
    session_factory: sessionmaker


def _queue_key(*, tenant_id: str, name: str) -> str:
    return f"ajenda:queue:{tenant_id}:{name}"


def _lease_key(*, tenant_id: str, task_id: uuid.UUID) -> str:
    return f"ajenda:queue:{tenant_id}:lease:{task_id}"


def _decode_task_ids(redis_client, *, tenant_id: str, name: str) -> list[str]:
    values = redis_client.lrange(_queue_key(tenant_id=tenant_id, name=name), 0, -1)
    task_ids: list[str] = []
    for raw in values:
        payload = json.loads(raw)
        task_ids.append(str(payload["task_id"]))
    return task_ids


def _pending_count(redis_client, *, tenant_id: str, task_id: uuid.UUID) -> int:
    return _decode_task_ids(redis_client, tenant_id=tenant_id, name="pending").count(str(task_id))


def _processing_count(redis_client, *, tenant_id: str, task_id: uuid.UUID) -> int:
    return _decode_task_ids(redis_client, tenant_id=tenant_id, name="processing").count(str(task_id))


def _create_running_task(pg_engine, queue_adapter, *, title: str) -> RunningTaskFixture:
    tenant_id = str(uuid.uuid4())
    worker_id = f"queue-corruption-worker-{tenant_id[:8]}"
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    setup_session = session_factory()
    try:
        tenant = Tenant(
            id=uuid.UUID(tenant_id),
            name=f"{title} Tenant",
            slug=f"queue-corruption-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)

        mission = Mission(
            tenant_id=tenant_id,
            objective=title,
            status="running",
        )
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title=title,
            description="Task proves recovery queue corruption boundaries",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={},
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id

        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )
        assert queued.ok is True
        setup_session.commit()
    finally:
        setup_session.close()

    start_session = session_factory()
    try:
        runtime = WorkerRuntimeService(start_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(claimed.metadata_json["worker_lease_id"])
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
    finally:
        start_session.close()

    stale_session = session_factory()
    try:
        lease = stale_session.get(WorkerLease, lease_id)
        assert lease is not None
        lease.heartbeat_at = datetime.now(UTC) - timedelta(seconds=120)
        stale_session.commit()
    finally:
        stale_session.close()

    return RunningTaskFixture(
        tenant_id=tenant_id,
        task_id=task_id,
        lease_id=lease_id,
        worker_id=worker_id,
        session_factory=session_factory,
    )


def _queue_message_for(session, *, task_id: uuid.UUID) -> QueueMessage:
    task = session.get(ExecutionTask, task_id)
    assert task is not None
    return QueueMessage(
        tenant_id=task.tenant_id,
        task_id=task.id,
        mission_id=task.mission_id,
        fleet_id=task.fleet_id,
        branch_id=task.branch_id,
        payload=dict(task.metadata_json),
        enqueued_at=datetime.now(UTC),
    )


def _recover(fixture: RunningTaskFixture, queue_adapter) -> None:
    recovery_session = fixture.session_factory()
    try:
        RuntimeMaintainer(
            session=recovery_session,
            queue=queue_adapter,
            expiry_seconds=30,
            max_retries=3,
        ).recover_expired_leases()
    finally:
        recovery_session.close()


def test_running_recovery_does_not_duplicate_when_payload_already_pending(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    fixture = _create_running_task(
        pg_engine,
        queue_adapter,
        title="running recovery pending duplicate guard",
    )

    session = fixture.session_factory()
    try:
        message = _queue_message_for(session, task_id=fixture.task_id)
        result = queue_adapter.enqueue_task(message)
        assert result.ok is True
    finally:
        session.close()

    assert _processing_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 1
    assert _pending_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 1

    _recover(fixture, queue_adapter)

    assert _processing_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 0
    assert _pending_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 1


def test_running_recovery_fails_closed_when_payload_missing_from_processing_and_pending(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    fixture = _create_running_task(
        pg_engine,
        queue_adapter,
        title="running recovery missing payload fails closed",
    )

    processing_key = _queue_key(tenant_id=fixture.tenant_id, name="processing")
    pending_key = _queue_key(tenant_id=fixture.tenant_id, name="pending")
    lease_key = _lease_key(tenant_id=fixture.tenant_id, task_id=fixture.task_id)
    redis_client.delete(processing_key, pending_key, lease_key)

    with pytest.raises(RuntimeError, match="task not found in processing queue"):
        _recover(fixture, queue_adapter)

    verify_session = fixture.session_factory()
    try:
        task = verify_session.get(ExecutionTask, fixture.task_id)
        lease = verify_session.get(WorkerLease, fixture.lease_id)
        assert task is not None
        assert task.status == ExecutionTaskState.RUNNING.value
        assert task.retry_count == 0
        assert lease is not None
        assert lease.status == WorkerLeaseState.ACTIVE.value
    finally:
        verify_session.close()

    assert _processing_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 0
    assert _pending_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 0


def test_running_recovery_converges_with_single_pending_payload_for_same_task(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    fixture = _create_running_task(
        pg_engine,
        queue_adapter,
        title="running recovery single pending convergence",
    )

    session = fixture.session_factory()
    try:
        message = _queue_message_for(session, task_id=fixture.task_id)
        first_duplicate = queue_adapter.enqueue_task(message)
        second_duplicate = queue_adapter.enqueue_task(message)
        assert first_duplicate.ok is True
        assert second_duplicate.ok is True
    finally:
        session.close()

    assert _processing_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 1
    assert _pending_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 2

    _recover(fixture, queue_adapter)

    assert _processing_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 0
    assert _pending_count(redis_client, tenant_id=fixture.tenant_id, task_id=fixture.task_id) == 1
