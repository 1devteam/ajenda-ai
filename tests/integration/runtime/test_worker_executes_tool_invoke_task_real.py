from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration


def test_worker_executes_tool_invoke_task_and_persists_evidence_shaped_output(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-tool-real"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(id=uuid.UUID(tenant_id), name="Tool Tenant", slug=f"tool-{tenant_id[:8]}", plan="free")
        )
        mission = Mission(tenant_id=tenant_id, objective="Tool mission", status="running")
        setup_session.add(mission)
        setup_session.flush()
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Tool invoke task",
            description="Task proves real tool.invoke execution through dispatcher",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "record.search",
                    "input": {"record_type": "account", "query": "Ajenda"},
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task_id)
        assert queued.ok is True
        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory, queue=queue_adapter, worker_id=worker_id, tenant_id=tenant_id
    ).execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        final_lease = verify_session.get(WorkerLease, lease_id)
        lineage = verify_session.scalars(
            select(LineageRecord).where(
                LineageRecord.tenant_id == tenant_id,
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            )
        ).all()
        evidence_records = verify_session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.execution_task_id == task_id,
                EvidenceRecord.evidence_source == "tool.invoke.record.search",
            )
        ).all()

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_task.metadata_json["handler_result"]["handler"] == "tool.invoke"
        assert final_task.metadata_json["output"]["count"] >= 1
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        payload = lineage[0].metadata_json
        assert lineage[0].relationship_reason == "tool action completed"
        assert payload["handler"] == "tool.invoke"
        assert payload["action"] == "record.search"
        assert payload["output"]["count"] >= 1
        assert payload["evidence"][0]["action_name"] == "record.search"
        assert payload["evidence"][0]["tenant_id"] == tenant_id
        assert len(evidence_records) == 1
        evidence = evidence_records[0]
        assert evidence.mission_id == final_task.mission_id
        assert evidence.evidence_type == "execution_trace"
        assert evidence.provenance_metadata["tool_evidence_type"] == "action_result"
        assert evidence.structured_payload["count"] >= 1
        assert evidence.materialization_reference["lineage_record_id"] == str(lineage[0].id)
        assert evidence.artifact_references[0]["lineage_record_id"] == str(lineage[0].id)
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()
