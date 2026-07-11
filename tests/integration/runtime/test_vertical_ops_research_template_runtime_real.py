"""Integration proof: vertical research template → queue → lease → tool.invoke → evidence.

ADR-0007 Phase B runtime proof for template ``vertical.research.v1`` (default step
``web.research``). Uses the existing ExecutionCoordinator + WorkerRuntimeService +
TaskDispatcher spine. No parallel agent swarm runtime.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.vertical_ops.template_service import (
    VERTICAL_TEMPLATE_METADATA_KEY,
    VerticalOpsTemplateService,
)
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration


def test_vertical_research_template_queues_claims_executes_and_persists_evidence(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant_id = str(uuid.uuid4())
    worker_id = "worker-vertical-ops-research"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(
            Tenant(
                id=uuid.UUID(tenant_id),
                name="Vertical Ops Tenant",
                slug=f"vertical-{tenant_id[:8]}",
                plan="free",
            )
        )
        mission = Mission(
            tenant_id=tenant_id,
            objective="Vertical research proof mission",
            status="planned",
            metadata_json={"schema_version": 1, "source": "vertical-ops-integration"},
            compliance_category="operational",
            jurisdiction="US-ALL",
        )
        setup_session.add(mission)
        setup_session.flush()

        quota = QuotaEnforcementService(setup_session)
        quota.check_and_record_mission_creation(uuid.UUID(tenant_id))
        # Pre-seed durable records so web.research does not seed inside the
        # dispatcher-held session (avoids long lock waits under concurrent heartbeat).
        activate_tenant_session(setup_session, tenant_id)
        TenantInternalRecordRepository(setup_session).seed_defaults_if_empty(tenant_id=tenant_id)
        setup_session.flush()

        service = VerticalOpsTemplateService()
        applied, queued = service.apply_and_queue(
            session=setup_session,
            queue=queue_adapter,
            mission=mission,
            template_id="vertical.research.v1",
            step_inputs={
                "research-internal": {
                    "query": "Acme competitors",
                    "company": "Acme",
                }
            },
            approved_by="vertical-ops-integration",
            approval_reason="Phase B research template runtime proof.",
            create_runtime_authority=False,
        )
        quota.check_and_record_task_creation(uuid.UUID(tenant_id), count=len(applied.created_task_ids))
        assert len(applied.created_task_ids) == 1
        assert queued.queued_task_ids == applied.created_task_ids
        assert queued.blocked_task_ids == ()
        task_id = applied.created_task_ids[0]

        template_meta = mission.metadata_json[VERTICAL_TEMPLATE_METADATA_KEY]
        assert template_meta["template_id"] == "vertical.research.v1"
        assert template_meta["grants_execution_authority"] is False
        assert template_meta["created_task_ids"] == [str(task_id)]

        planned_task = setup_session.get(ExecutionTask, task_id)
        assert planned_task is not None
        assert planned_task.metadata_json["task_type"] == "tool.invoke"
        assert planned_task.metadata_json["tool_invocation"]["action"] == "web.research"
        assert planned_task.metadata_json["vertical_role_key"] == "vertical.research"
        assert planned_task.metadata_json["template_id"] == "vertical.research.v1"
        assert planned_task.status == ExecutionTaskState.QUEUED.value

        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        assert claimed.id == task_id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
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
                EvidenceRecord.evidence_source == "tool.invoke.web.research",
            )
        ).all()

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        payload = lineage[0].metadata_json
        assert lineage[0].relationship_reason == "tool action completed"
        assert payload["handler"] == "tool.invoke"
        assert payload["action"] == "web.research"
        assert payload["output"]["query"] == "Acme competitors"
        assert payload["output"]["source"] == "ajenda_brain"
        assert payload["evidence"][0]["action_name"] == "web.research"
        assert payload["evidence"][0]["tenant_id"] == tenant_id
        assert len(evidence_records) == 1
        evidence = evidence_records[0]
        assert evidence.mission_id == final_task.mission_id
        assert evidence.evidence_type == "execution_trace"
        assert evidence.provenance_metadata["tool_evidence_type"] == "action_result"
        assert evidence.structured_payload["query"] == "Acme competitors"
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
        assert redis_client.get(f"ajenda:queue:{tenant_id}:lease:{task_id}") is None
    finally:
        verify_session.close()
