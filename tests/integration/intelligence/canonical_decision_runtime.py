"""Shared real-runtime proof builders for Decision intelligence integration tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.domain.worker_lease import WorkerLease
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.credentials._invoke_authority_helpers import (
    seed_capability_adapter_authority,
    side_effect_authorization,
)

EXECUTION_ACTION = "record.write"
MATERIALIZATION_ACTION = "analysis.materialize_decision_learning_signal"


@dataclass(frozen=True)
class CanonicalDecisionEpisode:
    """Durable identities emitted by one fully queue-authoritative episode."""

    mission_id: uuid.UUID
    supporting_evidence_id: uuid.UUID
    recommendation_evidence_id: uuid.UUID
    outcome_evidence_id: uuid.UUID
    execution_evidence_id: uuid.UUID
    learning_signal_evidence_id: uuid.UUID
    recommendation_task_id: uuid.UUID
    learning_signal: DecisionLearningSignal


def seed_execution_authority(*, factory: Any, tenant_id: str) -> dict[str, object]:
    """Create exact record.write promotion and side-effect authority for one tenant."""

    with factory() as authority_session:
        capability = authority_session.scalar(
            select(Capability).where(
                Capability.tenant_id == tenant_id,
                Capability.name == "integration_record_write",
                Capability.version == "1.0.0",
            )
        )
        adapter = (
            authority_session.scalar(
                select(CapabilityAdapter).where(
                    CapabilityAdapter.tenant_id == tenant_id,
                    CapabilityAdapter.capability_id == capability.id,
                    CapabilityAdapter.name == "integration_record_write_adapter",
                )
            )
            if capability is not None
            else None
        )
        if capability is None:
            references = seed_capability_adapter_authority(
                authority_session,
                tenant_id=tenant_id,
                action_name=EXECUTION_ACTION,
                side_effect_classification="non_idempotent_write",
            )
            authority_session.commit()
        else:
            assert adapter is not None
            references = {
                "capability_reference": {"capability_id": str(capability.id)},
                "adapter_reference": {"adapter_id": str(adapter.id)},
            }
    return {
        **references,
        **side_effect_authorization(allowed_actions=[EXECUTION_ACTION]),
    }


def execute_canonical_action(
    *,
    factory: Any,
    queue_adapter: Any,
    tenant_id: str,
    mission_id: uuid.UUID,
    action: str,
    action_input: dict[str, object],
    worker_label: str,
    runtime_authority_metadata: dict[str, object] | None = None,
) -> EvidenceRecord:
    """Run one action through queue, lease, dispatcher, lineage, and EvidenceBridge."""

    task_id = uuid.uuid4()
    worker_id = f"{worker_label}-{task_id}"
    with factory() as setup:
        setup.add(
            ExecutionTask(
                id=task_id,
                tenant_id=tenant_id,
                mission_id=mission_id,
                title=f"Canonical {action}",
                description=f"Real runtime proof for {action}",
                status=ExecutionTaskState.PLANNED.value,
                metadata_json={
                    "task_type": "tool.invoke",
                    "tool_invocation": {"schema_version": 1, "action": action, "input": action_input},
                    **(runtime_authority_metadata or {}),
                },
            )
        )
        setup.flush()
        QuotaEnforcementService(setup).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task_id)
        assert queued.ok is True
        runtime = WorkerRuntimeService(setup, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup.commit()

    TaskDispatcher(
        session_factory=factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    ).execute(task_id=task_id, lease_id=lease_id)

    with factory() as verify:
        task = verify.get(ExecutionTask, task_id)
        lease = verify.get(WorkerLease, lease_id)
        lineage = verify.scalars(
            select(LineageRecord).where(
                LineageRecord.task_id == task_id,
                LineageRecord.worker_lease_id == lease_id,
                LineageRecord.relationship_type == "task_output",
            )
        ).all()
        records = verify.scalars(select(EvidenceRecord).where(EvidenceRecord.execution_task_id == task_id)).all()
        assert task is not None and task.status == ExecutionTaskState.COMPLETED.value
        assert lease is not None and lease.status == WorkerLeaseState.RELEASED.value
        assert len(lineage) == 1
        assert len(records) == 1
        record = records[0]
        assert record.materialization_reference["lineage_record_id"] == str(lineage[0].id)
        assert record.materialization_reference["evidence_index"] == 0
        assert queue_adapter.pending_depth(tenant_id=tenant_id) == 0
        assert not queue_adapter.list_processing(tenant_id=tenant_id)
        verify.expunge(record)
        return record


def materialize_canonical_decision_episode(
    *,
    factory: Any,
    queue_adapter: Any,
    tenant_id: str,
    index: int,
) -> CanonicalDecisionEpisode:
    """Produce observation, Decision, execution, Outcome, and learning evidence canonically."""

    mission_id = uuid.uuid4()
    subject_id = f"opp-history-{index}"
    subject_ref = {"object_type": "opportunity", "object_id": subject_id}
    goal_id = "goal-increase-conversion"
    with factory() as setup:
        setup.add(Mission(id=mission_id, tenant_id=tenant_id, objective=f"Canonical episode {index}"))
        setup.flush()
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant_id,
            record_type="opportunity",
            record_id=subject_id,
            data={"name": f"Qualified opportunity {index}", "qualified": True},
        )
        setup.commit()

    supporting = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": subject_id},
        worker_label=f"source-{index}",
    )
    supporting_lineage = supporting.provenance_metadata["evidence_lineage"]
    recommendation_input: dict[str, object] = {
        "goal": "Increase conversion",
        "goal_ref": {
            "goal_id": goal_id,
            "objective_key": "increase_conversion",
            "name": "Increase conversion",
            "subject_refs": [subject_ref],
        },
        "subject_refs": [subject_ref],
        "options": [
            {
                "option_id": "followup",
                "label": "Recommend sales follow-up",
                "intervention_key": EXECUTION_ACTION,
            },
            {"option_id": "research", "label": "Research more", "intervention_key": "record.search"},
        ],
        "criteria": [{"criterion_id": "conversion", "label": "Conversion", "required": False}],
        "evidence": [
            {
                "evidence_id": str(supporting.id),
                "claim": "Qualified opportunity supports follow-up",
                "status": "known",
                "confidence": 0.9,
                "supports_option_ids": ["followup"],
                "supports_criterion_ids": ["conversion"],
                "lineage": supporting_lineage,
            }
        ],
    }
    recommendation = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="decision.recommend_next_action",
        action_input=recommendation_input,
        worker_label=f"decision-{index}",
    )
    execution_authority = seed_execution_authority(factory=factory, tenant_id=tenant_id)
    execution = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action=EXECUTION_ACTION,
        action_input={
            "record_type": "activity",
            "record_id": f"decision-execution-{index}",
            "data": {"status": "completed", "subject_id": subject_id},
        },
        worker_label=f"execution-{index}",
        runtime_authority_metadata=execution_authority,
    )
    executed_at = datetime.fromisoformat(str(execution.structured_payload["executed_at"]))
    observed_at = executed_at + timedelta(milliseconds=1)
    outcome = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": {
                "goal_id": goal_id,
                "objective_key": "increase_conversion",
                "name": "Increase conversion",
                "subject_refs": [subject_ref],
            },
            "subject_refs": [subject_ref],
            "baseline_kpis": [
                {
                    "kpi_id": "conversion",
                    "goal_id": goal_id,
                    "name": "Conversion",
                    "metric": "conversion",
                    "current_value": 0.5,
                    "target_value": 1.0,
                }
            ],
            "observed_kpis": [
                {
                    "kpi_id": "conversion",
                    "goal_id": goal_id,
                    "name": "Conversion",
                    "metric": "conversion",
                    "current_value": 1.0,
                    "target_value": 1.0,
                }
            ],
            "source_observed_at": observed_at.isoformat(),
            "evidence_ids": [str(execution.id)],
            "attribution_evidence": {
                "executed_at": executed_at.isoformat(),
                "execution_evidence_ids": [str(execution.id)],
                "expected_change_dimensions": ["conversion"],
                "observed_change_dimensions": ["conversion"],
                "confidence": 0.9,
            },
        },
        worker_label=f"outcome-{index}",
    )
    materialized = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action=MATERIALIZATION_ACTION,
        action_input={
            "recommendation_evidence_id": str(recommendation.id),
            "outcome_evaluation_evidence_id": str(outcome.id),
            "execution_evidence_ids": [str(execution.id)],
        },
        worker_label=f"materialization-{index}",
    )
    signal = DecisionLearningSignal.model_validate(materialized.structured_payload)
    assert signal.episode_reference is not None
    assert recommendation.execution_task_id is not None
    return CanonicalDecisionEpisode(
        mission_id=mission_id,
        supporting_evidence_id=supporting.id,
        recommendation_evidence_id=recommendation.id,
        outcome_evidence_id=outcome.id,
        execution_evidence_id=execution.id,
        learning_signal_evidence_id=materialized.id,
        recommendation_task_id=recommendation.execution_task_id,
        learning_signal=signal,
    )
