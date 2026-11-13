"""Real PostgreSQL proof for durable learning history through Knowledge Ledger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.domain.tenant import Tenant
from backend.services.durable_experience_consolidation import DurableLearningHistoryError
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.runtime_queue_dispatcher import RuntimeQueueDispatchService
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.intelligence.canonical_decision_runtime import (
    MATERIALIZATION_ACTION,
    materialize_canonical_decision_episode,
)
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration


def _ledger_counts(factory, tenant_id: str) -> tuple[int, int]:
    with factory() as verify:
        activate_tenant_session(verify, tenant_id)
        return (
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant_id)
            )
            or 0,
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeArtifactRecord)
                .where(KnowledgeArtifactRecord.tenant_id == tenant_id)
            )
            or 0,
        )


def test_real_cross_mission_history_is_canonical_tenant_isolated_and_replayable(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add_all(
            [
                Tenant(
                    id=uuid.UUID(tenant_a), name="Experience tenant", slug=f"experience-{tenant_a[:8]}", plan="free"
                ),
                Tenant(id=uuid.UUID(tenant_b), name="Other tenant", slug=f"other-{tenant_b[:8]}", plan="free"),
            ]
        )
        setup.commit()

    episodes_a = [
        materialize_canonical_decision_episode(
            factory=factory,
            queue_adapter=queue_adapter,
            tenant_id=tenant_a,
            index=index,
        )
        for index in (1, 2, 3)
    ]
    materialize_canonical_decision_episode(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_b,
        index=4,
    )
    assert len({episode.mission_id for episode in episodes_a}) == 3

    with factory() as verify:
        activation_tasks = [
            task
            for task in verify.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant_a)).all()
            if (task.metadata_json or {}).get("tool_invocation", {}).get("action")
            == "knowledge.consolidate_learning_history"
        ]
        assert len(activation_tasks) == 1
        assert activation_tasks[0].status == ExecutionTaskState.PENDING_REVIEW.value
        assert set(activation_tasks[0].metadata_json["learning_consolidation_activation"]["source_evidence_ids"]) == {
            str(episode.learning_signal_evidence_id) for episode in episodes_a
        }

    context = ActionRuntimeContext(
        tenant_id=tenant_a,
        task_id=uuid.uuid4(),
        worker_id="integration-worker",
        lease_id="integration-lease",
        session_factory=factory,
    )
    invocation = ToolInvocation(action="knowledge.consolidate_learning_history", input={})
    registry = get_default_action_registry(rebuild=True)
    first = registry.invoke(invocation, context)
    replay = registry.invoke(invocation, context)

    assert set(first.output["records_inspected"]) == {
        str(episode.learning_signal_evidence_id) for episode in episodes_a
    }
    earliest = datetime.fromisoformat(
        first.output["experience"]["pattern_candidates"][0]["earliest_evaluated_at"].replace("Z", "+00:00")
    )
    assert earliest == min(episode.learning_signal.evaluated_at for episode in episodes_a)
    assert first.output["qualifications"][0]["qualification"]["status"] == "qualified"
    assert first.output["qualifications"][0]["ledger_write"]["status"] == "recorded"
    assert replay.output["qualifications"][0]["ledger_write"]["status"] == "already_recorded"
    assert _ledger_counts(factory, tenant_a) == (1, 1)
    assert _ledger_counts(factory, tenant_b) == (0, 0)

    forged_id = uuid.uuid4()
    with factory() as setup:
        setup.add(
            EvidenceRecord(
                id=forged_id,
                tenant_id=tenant_a,
                mission_id=episodes_a[0].mission_id,
                evidence_type="execution_trace",
                evidence_source="public_evidence_contract",
                summary="Caller-claimed learning signal",
                structured_payload=episodes_a[0].learning_signal.model_dump(mode="json"),
                provenance_metadata={
                    "action_name": MATERIALIZATION_ACTION,
                    "evidence_role": "decision_learning_signal",
                },
                materialization_reference={"action": MATERIALIZATION_ACTION},
            )
        )
        setup.commit()

    with pytest.raises(DurableLearningHistoryError, match=str(forged_id)):
        registry.invoke(invocation, context)
    assert _ledger_counts(factory, tenant_a) == (1, 1)


def test_recognition_requires_human_approval_before_runtime_consolidation(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant = str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant), name="Activation tenant", slug=f"activation-{tenant[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant)
        persist_test_operating_charter(
            setup,
            tenant_id=tenant,
            allow_perform=("knowledge.consolidate_learning_history",),
        )
        setup.commit()

    episodes = [
        materialize_canonical_decision_episode(
            factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=index
        )
        for index in (21, 22, 23)
    ]
    with factory() as setup:
        activation = next(
            task
            for task in setup.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant)).all()
            if (task.metadata_json or {}).get("tool_invocation", {}).get("action")
            == "knowledge.consolidate_learning_history"
        )
        assert activation.status == ExecutionTaskState.PENDING_REVIEW.value
        assert _ledger_counts(factory, tenant) == (0, 0)
        admitted = ExecutionCoordinator(setup, queue_adapter).approve_review_and_queue(
            tenant_id=tenant,
            task_id=activation.id,
            actor="human:knowledge-reviewer",
            approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        assert admitted.ok is True
        setup.commit()
        RuntimeQueueDispatchService(setup, queue_adapter).publish_due()
        runtime = WorkerRuntimeService(setup, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant, worker_id="knowledge-activation-worker")
        assert claimed is not None and claimed.id == activation.id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant, lease_id=lease_id, worker_id="knowledge-activation-worker")
        runtime.start_execution(tenant_id=tenant, lease_id=lease_id, worker_id="knowledge-activation-worker")
        setup.commit()

    TaskDispatcher(
        session_factory=factory,
        queue=queue_adapter,
        worker_id="knowledge-activation-worker",
        tenant_id=tenant,
    ).execute(task_id=activation.id, lease_id=lease_id)

    with factory() as verify:
        completed = verify.get(ExecutionTask, activation.id)
        assert completed is not None and completed.status == ExecutionTaskState.COMPLETED.value, (
            (completed.metadata_json or {}).get("failure") if completed is not None else None
        )
        assert _ledger_counts(factory, tenant) == (1, 1)
        assert set(completed.metadata_json["handler_result"]["output"]["records_inspected"]) == {
            str(item.learning_signal_evidence_id) for item in episodes
        }
