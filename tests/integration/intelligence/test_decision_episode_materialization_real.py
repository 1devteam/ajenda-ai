"""Real PostgreSQL proof for authoritative decision episode materialization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.outcome import AttributionAssessment, OutcomeEvaluation, OutcomeStatus
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation

pytestmark = pytest.mark.integration

DECIDED_AT = datetime(2026, 8, 12, 10, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 8, 12, 10, 5, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 12, 11, tzinfo=UTC)


def _row_counts(factory, tenant_id: str) -> tuple[int, int, int]:
    with factory() as session:
        activate_tenant_session(session, tenant_id)
        return (
            session.scalar(select(func.count()).select_from(Mission).where(Mission.tenant_id == tenant_id)) or 0,
            session.scalar(select(func.count()).select_from(ExecutionTask).where(ExecutionTask.tenant_id == tenant_id))
            or 0,
            session.scalar(
                select(func.count()).select_from(EvidenceRecord).where(EvidenceRecord.tenant_id == tenant_id)
            )
            or 0,
        )


def test_materialization_action_reads_real_tenant_artifacts_without_mutation(pg_engine) -> None:
    tenant_a = f"tenant-{uuid.uuid4()}"
    tenant_b = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    mission_id = uuid.uuid4()
    recommendation_task_id = uuid.uuid4()
    execution_task_id = uuid.uuid4()
    supporting_id = uuid.uuid4()
    recommendation_id = uuid.uuid4()
    outcome_id = uuid.uuid4()
    execution_id = uuid.uuid4()

    supporting_lineage = EvidenceLineage(
        artifact_evidence_id=str(supporting_id),
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        root_evidence_ids=(str(supporting_id),),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    recommendation_input = {
        "goal": "Improve qualification",
        "options": [
            {
                "option_id": "discovery",
                "label": "Discovery",
                "intervention_key": "sales.schedule_discovery",
            }
        ],
        "criteria": [{"criterion_id": "fit", "label": "Fit"}],
        "evidence": [
            {
                "evidence_id": str(supporting_id),
                "claim": "Account is qualified",
                "supports_option_ids": ["discovery"],
                "supports_criterion_ids": ["fit"],
                "lineage": supporting_lineage.model_dump(mode="json"),
            }
        ],
    }
    recommendation_payload = {
        "decided_at": DECIDED_AT.isoformat(),
        "goal": "Improve qualification",
        "recommendation": "discovery",
        "intervention_key": "sales.schedule_discovery",
        "supporting_evidence_ids": [str(supporting_id)],
        "option_scores": [{"option_id": "discovery", "total_score": 1}],
        "uncertainty": [],
        "algorithm": {"name": "weighted_criterion_evidence_v1", "version": "1"},
    }
    recommendation_lineage = EvidenceLineage(
        artifact_evidence_id=str(recommendation_id),
        origin_type=EvidenceOriginType.SYSTEM_COMPUTATION,
        parent_evidence_ids=(str(supporting_id),),
        resolution=EvidenceLineageResolution.PARTIAL,
    )
    outcome = OutcomeEvaluation(
        outcome_evaluation_id="outcome-real",
        status=OutcomeStatus.ACHIEVED,
        attribution=AttributionAssessment.TEMPORAL_ASSOCIATION,
        confidence=0.8,
        observed_at=OBSERVED_AT,
        evaluated_at=OBSERVED_AT,
    )

    with factory() as setup:
        activate_tenant_session(setup, tenant_a)
        setup.add(Mission(id=mission_id, tenant_id=tenant_a, objective="Decision episode proof"))
        setup.flush()
        setup.add(
            ExecutionTask(
                id=recommendation_task_id,
                tenant_id=tenant_a,
                mission_id=mission_id,
                title="Recommend",
                description="Create durable recommendation",
                metadata_json={
                    "tool_invocation": {
                        "action": "decision.recommend_next_action",
                        "input": recommendation_input,
                    }
                },
            )
        )
        setup.flush()
        setup.add_all(
            [
                EvidenceRecord(
                    id=supporting_id,
                    tenant_id=tenant_a,
                    mission_id=mission_id,
                    evidence_type="execution_trace",
                    evidence_source="crm",
                    summary="Qualified account",
                    structured_payload={"qualified": True},
                    provenance_metadata={"evidence_lineage": supporting_lineage.model_dump(mode="json")},
                    created_at=datetime(2026, 8, 12, 12, 30, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id=recommendation_id,
                    tenant_id=tenant_a,
                    mission_id=mission_id,
                    execution_task_id=recommendation_task_id,
                    evidence_type="execution_trace",
                    evidence_source="decision_actions",
                    summary="Recommended discovery",
                    structured_payload=recommendation_payload,
                    provenance_metadata={
                        "action_name": "decision.recommend_next_action",
                        "tool_provider": "ajenda_decision",
                        "evidence_role": "decision_recommendation_result",
                        "evidence_lineage": recommendation_lineage.model_dump(mode="json"),
                    },
                    confidence=0.8,
                    created_at=datetime(2026, 8, 12, 12, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id=outcome_id,
                    tenant_id=tenant_a,
                    mission_id=mission_id,
                    evidence_type="execution_trace",
                    evidence_source="analysis_actions",
                    summary="Outcome evaluated",
                    structured_payload=outcome.model_dump(mode="json"),
                    provenance_metadata={"action_name": "analysis.evaluate_outcome"},
                    created_at=datetime(2026, 8, 12, 11, 2, tzinfo=UTC),
                ),
                EvidenceRecord(
                    id=execution_id,
                    tenant_id=tenant_a,
                    mission_id=mission_id,
                    execution_task_id=execution_task_id,
                    evidence_type="execution_trace",
                    evidence_source="sales",
                    summary="Discovery scheduled",
                    structured_payload={"executed_at": EXECUTED_AT.isoformat()},
                    provenance_metadata={"action_name": "sales.schedule_discovery"},
                    created_at=datetime(2026, 8, 12, 13, tzinfo=UTC),
                ),
            ]
        )
        setup.add(
            ExecutionTask(
                id=execution_task_id,
                tenant_id=tenant_a,
                mission_id=mission_id,
                title="Execute",
                description="Schedule discovery",
            )
        )
        setup.commit()

    request = {
        "recommendation_evidence_id": str(recommendation_id),
        "outcome_evaluation_evidence_id": str(outcome_id),
        "execution_evidence_ids": [str(execution_id)],
    }
    registry = get_default_action_registry(rebuild=True)
    definition = registry.get("analysis.materialize_decision_learning_signal")
    assert definition.side_effect_class == SideEffectClass.INTERNAL_READ
    before = _row_counts(factory, tenant_a)
    activated_tenants: list[str] = []

    def capture_tenant_activation(_conn, _cursor, statement, parameters, _context, _executemany) -> None:
        if "set_config('app.current_tenant_id'" in statement:
            activated_tenants.append(parameters["tenant_id"])

    event.listen(pg_engine, "before_cursor_execute", capture_tenant_activation)
    try:
        context = ActionRuntimeContext(
            tenant_id=tenant_a,
            task_id=uuid.uuid4(),
            mission_id=mission_id,
            worker_id="worker",
            lease_id="lease",
            session_factory=factory,
        )
        first = registry.invoke(
            ToolInvocation(action="analysis.materialize_decision_learning_signal", input=request), context
        )
        replay = registry.invoke(
            ToolInvocation(action="analysis.materialize_decision_learning_signal", input=request), context
        )
        with pytest.raises(ValueError, match="recommendation artifact is inaccessible"):
            registry.invoke(
                ToolInvocation(action="analysis.materialize_decision_learning_signal", input=request),
                context.model_copy(update={"tenant_id": tenant_b}),
            )
    finally:
        event.remove(pg_engine, "before_cursor_execute", capture_tenant_activation)

    assert first.side_effect_class == SideEffectClass.INTERNAL_READ
    assert first.evidence[0].side_effect_class == SideEffectClass.INTERNAL_READ
    assert first.output["decision_id"] == replay.output["decision_id"]
    assert first.output["signal_id"] == replay.output["signal_id"]
    assert first.output["episode_reference"]["episode_id"] == replay.output["episode_reference"]["episode_id"]
    assert f"evidence:{supporting_id}" in first.records_inspected
    assert f"execution_task:{recommendation_task_id}" in first.records_inspected
    assert first.records_inspected == first.evidence[0].records_inspected
    assert activated_tenants.count(tenant_a) >= 2
    assert tenant_b in activated_tenants
    assert _row_counts(factory, tenant_a) == before == (1, 2, 4)
