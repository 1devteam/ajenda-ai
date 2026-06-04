from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.tools.local_records import default_local_record_provider
from backend.services.tools.schemas import LocalRecord
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher


def test_worker_dispatcher_executes_queued_tool_invoke_task_real(pg_engine, queue_adapter, redis_client) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-tool-invoke-real"
    session_factory = sessionmaker(
        bind=pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    default_local_record_provider().seed(
        tenant_id=tenant_id,
        records=[
            LocalRecord(
                tenant_id=tenant_id,
                record_type="lead",
                record_id="lead-real-1",
                name="Runtime Proof Lead",
                fields={"budget": 50000, "employee_count": 200, "urgency": "high"},
            )
        ],
    )

    setup_session = session_factory()
    try:
        tenant = Tenant(
            id=uuid.UUID(tenant_id),
            name="Tool Invoke Tenant",
            slug=f"tool-invoke-{tenant_id[:8]}",
            plan="free",
        )
        setup_session.add(tenant)
        mission = Mission(tenant_id=tenant_id, objective="Tool invoke mission", status="running")
        setup_session.add(mission)
        setup_session.flush()

        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="Tool invoke task",
            description="Execute record search through tool.invoke",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "record.search",
                    "input": {"record_type": "lead", "query": "Runtime Proof"},
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

    dispatcher = TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    )
    dispatcher.execute(task_id=task_id, lease_id=lease_id)

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

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        output = lineage[0].metadata_json
        assert lineage[0].relationship_reason == "tool action completed"
        assert output["handler"] == "tool.invoke"
        assert output["action"] == "record.search"
        assert output["output"]["count"] == 1
        assert output["output"]["records"][0]["record_id"] == "lead-real-1"
        assert output["evidence"][0]["evidence_source"] == "tool.invoke.record.search"
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()
