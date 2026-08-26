from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.api.routes import observability as exporter
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.queue.base import QueueMessage

pytestmark = pytest.mark.integration


def _cleanup_tenant_runtime_rows(session_factory: Callable[[], Session], tenant_id: str) -> None:
    cleanup_session = session_factory()
    try:
        cleanup_session.execute(delete(WorkerLease).where(WorkerLease.tenant_id == tenant_id))
        cleanup_session.execute(delete(ExecutionTask).where(ExecutionTask.tenant_id == tenant_id))
        cleanup_session.execute(delete(Mission).where(Mission.tenant_id == tenant_id))
        cleanup_session.execute(delete(Tenant).where(Tenant.id == uuid.UUID(tenant_id)))
        cleanup_session.commit()
    finally:
        cleanup_session.close()


def test_metrics_snapshot_does_not_trigger_runtime_recovery_or_mutate_stale_lease_state(
    pg_engine,
    queue_adapter,
) -> None:
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    try:
        setup_session = session_factory()
        try:
            setup_session.add(
                Tenant(
                    id=uuid.UUID(tenant_id),
                    name="Metrics Runtime Tenant",
                    slug=f"metrics-runtime-{tenant_id[:8]}",
                    plan="free",
                )
            )
            mission = Mission(tenant_id=tenant_id, objective="metrics non-mutating", status="running")
            setup_session.add(mission)
            setup_session.flush()

            task = ExecutionTask(
                tenant_id=tenant_id,
                mission_id=mission.id,
                title="stale claimed task",
                description="prove metrics endpoint does not recover stale work",
                status=ExecutionTaskState.PLANNED.value,
                metadata_json={},
                compliance_category="operational",
                jurisdiction="US-ALL",
                requires_human_review=False,
            )
            setup_session.add(task)
            setup_session.flush()

            lease = WorkerLease(
                tenant_id=tenant_id,
                task_id=task.id,
                holder_identity="metrics-no-mutate-worker",
                status=WorkerLeaseState.ACTIVE.value,
                heartbeat_at=datetime.now(UTC) - timedelta(minutes=10),
            )
            setup_session.add(lease)

            task.status = ExecutionTaskState.CLAIMED.value
            task.metadata_json["worker_lease_id"] = str(lease.id)

            setup_session.commit()
            task_id = task.id
            lease_id = lease.id
        finally:
            setup_session.close()

        snapshot_session = session_factory()
        try:
            before_task = snapshot_session.get(ExecutionTask, task_id)
            before_lease = snapshot_session.get(WorkerLease, lease_id)
            assert before_task is not None
            assert before_lease is not None

            before_task_status = before_task.status
            before_lease_status = before_lease.status
            before_lease_heartbeat = before_lease.heartbeat_at

            snapshot = exporter._collect_snapshot(snapshot_session)
            assert snapshot.active_leases >= 1

            snapshot_session.expire_all()
            after_task = snapshot_session.get(ExecutionTask, task_id)
            after_lease = snapshot_session.get(WorkerLease, lease_id)
            assert after_task is not None
            assert after_lease is not None

            assert after_task.status == before_task_status
            assert after_lease.status == before_lease_status
            assert after_lease.heartbeat_at == before_lease_heartbeat
        finally:
            snapshot_session.close()
    finally:
        _cleanup_tenant_runtime_rows(session_factory, tenant_id)


def test_dead_lettered_task_is_not_reprocessed_by_claim_path(pg_engine, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    pending_key = f"ajenda:queue:{tenant_id}:pending"
    processing_key = f"ajenda:queue:{tenant_id}:processing"
    dead_letter_key = f"ajenda:queue:{tenant_id}:dead_letter"

    try:
        setup_session = session_factory()
        try:
            setup_session.add(
                Tenant(
                    id=uuid.UUID(tenant_id),
                    name="Dead Letter Claim Isolation Tenant",
                    slug=f"dead-letter-claim-{tenant_id[:8]}",
                    plan="free",
                )
            )
            mission = Mission(tenant_id=tenant_id, objective="dead-letter no reprocess", status="running")
            setup_session.add(mission)
            setup_session.flush()

            task = ExecutionTask(
                tenant_id=tenant_id,
                mission_id=mission.id,
                title="dead-letter terminal task",
                description="must not be claimed after dead-letter transition",
                status=ExecutionTaskState.QUEUED.value,
                metadata_json={"task_type": "echo", "input": {"message": "dlq-proof"}},
                compliance_category="operational",
                jurisdiction="US-ALL",
                requires_human_review=False,
            )
            setup_session.add(task)
            setup_session.flush()
            task_id = task.id
            mission_id = mission.id
            setup_session.commit()
        finally:
            setup_session.close()

        msg = QueueMessage(
            tenant_id=tenant_id,
            task_id=task_id,
            mission_id=mission_id,
            fleet_id=None,
            branch_id=None,
            payload={"task_type": "echo", "input": {"message": "dlq-proof"}},
            enqueued_at=datetime.now(UTC),
        )
        assert queue_adapter.enqueue_task(msg).ok is True

        claimed = queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-dead-letter")
        assert claimed is not None
        assert claimed.task_id == task_id

        assert (
            queue_adapter.move_owned_to_dead_letter(
                tenant_id=tenant_id,
                task_id=task_id,
                worker_id="worker-dead-letter",
                reason="integration-proof",
            ).ok
            is True
        )

        with session_factory() as status_session:
            persisted_task = status_session.get(ExecutionTask, task_id)
            assert persisted_task is not None
            persisted_task.status = ExecutionTaskState.DEAD_LETTERED.value
            status_session.commit()

        before_pending = redis_client.lrange(pending_key, 0, -1)
        before_processing = redis_client.lrange(processing_key, 0, -1)
        before_dead_letter = redis_client.lrange(dead_letter_key, 0, -1)

        assert before_pending == []
        assert before_processing == []
        assert len(before_dead_letter) >= 1
        assert any(str(task_id) == json.loads(payload)["task_id"] for payload in before_dead_letter)

        assert queue_adapter.claim_task(tenant_id=tenant_id, worker_id="worker-no-reprocess") is None

        after_pending = redis_client.lrange(pending_key, 0, -1)
        after_processing = redis_client.lrange(processing_key, 0, -1)
        after_dead_letter = redis_client.lrange(dead_letter_key, 0, -1)

        assert after_pending == before_pending
        assert after_processing == before_processing
        assert after_dead_letter == before_dead_letter

        verify_session = session_factory()
        try:
            leases = verify_session.scalars(
                select(WorkerLease).where(WorkerLease.tenant_id == tenant_id, WorkerLease.task_id == task_id)
            ).all()
            task = verify_session.get(ExecutionTask, task_id)
            assert task is not None
            assert task.status == ExecutionTaskState.DEAD_LETTERED.value
            assert leases == []
        finally:
            verify_session.close()
    finally:
        redis_client.delete(pending_key, processing_key, dead_letter_key)
        _cleanup_tenant_runtime_rows(session_factory, tenant_id)
