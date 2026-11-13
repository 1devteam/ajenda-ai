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


@pytest.mark.parametrize(
    "in_flight_state",
    (
        ExecutionTaskState.QUEUED,
        ExecutionTaskState.CLAIMED,
        ExecutionTaskState.RUNNING,
    ),
)
def test_late_learning_creates_successor_review_instead_of_rewriting_in_flight_scope(
    pg_engine, queue_adapter, redis_client, in_flight_state: ExecutionTaskState
) -> None:
    """Real persisted signals must not be attached to an already-approved review.

    Model each reachable in-flight state on the persisted task rather than
    launching a second concurrent worker: the invariant under test belongs to
    completion-time admission, not lease scheduling or consolidation scoring.
    """
    tenant = str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant), name="Late learning", slug=f"late-{tenant[:8]}", plan="free"))
        setup.commit()

    original = [
        materialize_canonical_decision_episode(
            factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=index
        )
        for index in (341, 342, 343)
    ]
    original_ids = {str(episode.learning_signal_evidence_id) for episode in original}
    with factory() as setup:
        activate_tenant_session(setup, tenant)
        reviews = [
            task
            for task in setup.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant))
            if (task.metadata_json or {}).get("tool_invocation", {}).get("action")
            == "knowledge.consolidate_learning_history"
        ]
        assert len(reviews) == 1
        first = reviews[0]
        assert first.status == ExecutionTaskState.PENDING_REVIEW.value
        assert set(first.metadata_json["learning_consolidation_activation"]["source_evidence_ids"]) == original_ids
        original_task_id = first.id
        # The state mutation isolates the post-approval coalescing boundary:
        # queue/claim/lease behavior is covered by the existing runtime test.
        first.status = in_flight_state.value
        setup.commit()

    late = materialize_canonical_decision_episode(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=344
    )
    late_id = str(late.learning_signal_evidence_id)
    with factory() as verify:
        activate_tenant_session(verify, tenant)
        reviews = [
            task
            for task in verify.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant))
            if (task.metadata_json or {}).get("tool_invocation", {}).get("action")
            == "knowledge.consolidate_learning_history"
        ]
        assert len(reviews) == 2
        first = next(task for task in reviews if task.id == original_task_id)
        successor = next(task for task in reviews if task.id != original_task_id)
        assert first.status == in_flight_state.value
        assert set(first.metadata_json["learning_consolidation_activation"]["source_evidence_ids"]) == original_ids
        assert successor.status == ExecutionTaskState.PENDING_REVIEW.value
        assert successor.requires_human_review is True
        assert successor.metadata_json["learning_consolidation_activation"]["source_evidence_ids"] == [late_id]
        assert "ability_authorization" not in successor.metadata_json.get("execution_constraints", {})
        successor_id = successor.id

    # Later signals may still coalesce into the *new* unapproved review.
    another = materialize_canonical_decision_episode(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=345
    )
    with factory() as verify:
        activate_tenant_session(verify, tenant)
        reviews = [
            task
            for task in verify.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant))
            if (task.metadata_json or {}).get("tool_invocation", {}).get("action")
            == "knowledge.consolidate_learning_history"
        ]
        assert len(reviews) == 2
        successor = next(task for task in reviews if task.id == successor_id)
        assert successor.status == ExecutionTaskState.PENDING_REVIEW.value
        assert set(successor.metadata_json["learning_consolidation_activation"]["source_evidence_ids"]) == {
            late_id,
            str(another.learning_signal_evidence_id),
        }
        assert _ledger_counts(factory, tenant) == (0, 0)


def test_successive_learning_cycles_require_distinct_approval_and_preserve_history(
    pg_engine, queue_adapter, redis_client
) -> None:
    """A completed approved review must not consume or authorize later learning."""
    tenant = str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant), name="Successive learning", slug=f"cycles-{tenant[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant)
        persist_test_operating_charter(
            setup,
            tenant_id=tenant,
            allow_perform=("knowledge.consolidate_learning_history",),
        )
        setup.commit()

    def reviews(session) -> list[ExecutionTask]:
        return [
            task
            for task in session.scalars(select(ExecutionTask).where(ExecutionTask.tenant_id == tenant)).all()
            if (task.metadata_json or {}).get("tool_invocation", {}).get("action")
            == "knowledge.consolidate_learning_history"
        ]

    def approve_and_execute(task_id: uuid.UUID, *, worker_id: str) -> dict:
        with factory() as session:
            activate_tenant_session(session, tenant)
            task = session.get(ExecutionTask, task_id)
            assert task is not None and task.status == ExecutionTaskState.PENDING_REVIEW.value
            admission = ExecutionCoordinator(session, queue_adapter).approve_review_and_queue(
                tenant_id=tenant,
                task_id=task_id,
                actor="human:knowledge-reviewer",
                approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            assert admission.ok is True
            session.commit()
            RuntimeQueueDispatchService(session, queue_adapter).publish_due()
            runtime = WorkerRuntimeService(session, queue_adapter)
            claimed = runtime.claim_next_task(tenant_id=tenant, worker_id=worker_id)
            assert claimed is not None and claimed.id == task_id
            lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
            runtime.heartbeat(tenant_id=tenant, lease_id=lease_id, worker_id=worker_id)
            runtime.start_execution(tenant_id=tenant, lease_id=lease_id, worker_id=worker_id)
            session.commit()
        TaskDispatcher(
            session_factory=factory,
            queue=queue_adapter,
            worker_id=worker_id,
            tenant_id=tenant,
        ).execute(task_id=task_id, lease_id=lease_id)
        with factory() as verify:
            activate_tenant_session(verify, tenant)
            completed = verify.get(ExecutionTask, task_id)
            assert completed is not None
            assert completed.status == ExecutionTaskState.COMPLETED.value, (
                (completed.metadata_json or {}).get("failure")
            )
            return dict(completed.metadata_json["handler_result"]["output"])

    first_episodes = [
        materialize_canonical_decision_episode(
            factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=index
        )
        for index in (401, 402, 403)
    ]
    first_ids = {str(item.learning_signal_evidence_id) for item in first_episodes}
    with factory() as session:
        activate_tenant_session(session, tenant)
        first_reviews = reviews(session)
        assert len(first_reviews) == 1
        first = first_reviews[0]
        assert first.status == ExecutionTaskState.PENDING_REVIEW.value
        assert set(first.metadata_json["learning_consolidation_activation"]["source_evidence_ids"]) == first_ids
        first_task_id = first.id
    assert _ledger_counts(factory, tenant) == (0, 0)
    first_output = approve_and_execute(first_task_id, worker_id="knowledge-cycle-1")
    assert set(first_output["records_inspected"]) == first_ids
    assert first_output["qualifications"][0]["qualification"]["status"] == "qualified"
    assert _ledger_counts(factory, tenant) == (1, 1)

    new_episode = materialize_canonical_decision_episode(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, index=404
    )
    late_id = str(new_episode.learning_signal_evidence_id)
    with factory() as session:
        activate_tenant_session(session, tenant)
        all_reviews = reviews(session)
        assert len(all_reviews) == 2
        previous = next(task for task in all_reviews if task.id == first_task_id)
        successor = next(task for task in all_reviews if task.id != first_task_id)
        assert previous.status == ExecutionTaskState.COMPLETED.value
        assert set(previous.metadata_json["learning_consolidation_activation"]["source_evidence_ids"]) == first_ids
        assert successor.status == ExecutionTaskState.PENDING_REVIEW.value
        assert successor.requires_human_review is True
        assert successor.metadata_json["learning_consolidation_activation"]["source_evidence_ids"] == [late_id]
        assert "ability_authorization" not in successor.metadata_json.get("execution_constraints", {})
        second_task_id = successor.id
    assert _ledger_counts(factory, tenant) == (1, 1)

    second_output = approve_and_execute(second_task_id, worker_id="knowledge-cycle-2")
    assert set(second_output["records_inspected"]) == first_ids | {late_id}
    assert second_output["qualifications"]
    assert all(
        item["qualification"]["status"] == "qualified"
        for item in second_output["qualifications"]
    )
    with factory() as session:
        activate_tenant_session(session, tenant)
        final_reviews = reviews(session)
        assert len(final_reviews) == 2
        assert all(task.status == ExecutionTaskState.COMPLETED.value for task in final_reviews)
    qualifications, artifacts = _ledger_counts(factory, tenant)
    assert qualifications >= 1
    assert artifacts >= 1
