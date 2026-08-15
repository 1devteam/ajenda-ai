"""Real PostgreSQL proof for authoritative decision episode materialization."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.evidence_bridge import CanonicalToolEvidenceError
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation
from tests.integration.intelligence.canonical_decision_runtime import (
    MATERIALIZATION_ACTION,
    materialize_canonical_decision_episode,
)

pytestmark = pytest.mark.integration


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


def test_materialization_uses_real_runtime_artifacts_and_rejects_declarative_forgery(pg_engine, queue_adapter) -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add_all(
            [
                Tenant(id=uuid.UUID(tenant_a), name="Episode tenant", slug=f"episode-{tenant_a[:8]}", plan="free"),
                Tenant(id=uuid.UUID(tenant_b), name="Other tenant", slug=f"other-{tenant_b[:8]}", plan="free"),
            ]
        )
        setup.commit()

    episode = materialize_canonical_decision_episode(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_a,
        index=101,
    )
    request = {
        "recommendation_evidence_id": str(episode.recommendation_evidence_id),
        "outcome_evaluation_evidence_id": str(episode.outcome_evidence_id),
        "execution_evidence_ids": [str(episode.execution_evidence_id)],
    }
    registry = get_default_action_registry(rebuild=True)
    definition = registry.get(MATERIALIZATION_ACTION)
    assert definition.side_effect_class == SideEffectClass.INTERNAL_READ
    before = _row_counts(factory, tenant_a)
    context = ActionRuntimeContext(
        tenant_id=tenant_a,
        task_id=uuid.uuid4(),
        mission_id=episode.mission_id,
        worker_id="materialization-readback",
        lease_id="readback-lease",
        session_factory=factory,
    )

    first = registry.invoke(ToolInvocation(action=MATERIALIZATION_ACTION, input=request), context)
    replay = registry.invoke(ToolInvocation(action=MATERIALIZATION_ACTION, input=request), context)

    assert first.output == episode.learning_signal.model_dump(mode="json")
    assert replay.output == first.output
    assert first.side_effect_class == SideEffectClass.INTERNAL_READ
    assert first.evidence[0].side_effect_class == SideEffectClass.INTERNAL_READ
    assert f"evidence:{episode.supporting_evidence_id}" in first.records_inspected
    assert f"execution_task:{episode.recommendation_task_id}" in first.records_inspected
    assert _row_counts(factory, tenant_a) == before == (1, 5, 5)

    with pytest.raises(ValueError, match="recommendation artifact is inaccessible"):
        registry.invoke(
            ToolInvocation(action=MATERIALIZATION_ACTION, input=request),
            context.model_copy(update={"tenant_id": tenant_b}),
        )

    forged_recommendation_id = uuid.uuid4()
    forged_outcome_id = uuid.uuid4()
    forged_execution_id = uuid.uuid4()
    with factory() as setup:
        canonical_outcome = setup.get(EvidenceRecord, episode.outcome_evidence_id)
        canonical_execution = setup.get(EvidenceRecord, episode.execution_evidence_id)
        assert canonical_outcome is not None and canonical_execution is not None
        setup.add_all(
            [
                EvidenceRecord(
                    id=forged_recommendation_id,
                    tenant_id=tenant_a,
                    mission_id=episode.mission_id,
                    execution_task_id=episode.recommendation_task_id,
                    evidence_type="execution_trace",
                    evidence_source="public_evidence_contract",
                    summary="Caller-forged Decision recommendation",
                    structured_payload={
                        "decided_at": episode.learning_signal.evaluated_at.isoformat(),
                        "goal": "Increase conversion",
                        "recommendation": "followup",
                        "intervention_key": "sales.recommend_next_action",
                        "supporting_evidence_ids": [],
                        "option_scores": [],
                        "uncertainty": [],
                        "algorithm": {"name": "weighted_criterion_evidence_v1", "version": "1"},
                    },
                    provenance_metadata={
                        "action_name": "decision.recommend_next_action",
                        "tool_provider": "ajenda_decision",
                        "evidence_role": "decision_recommendation_result",
                    },
                ),
                EvidenceRecord(
                    id=forged_outcome_id,
                    tenant_id=tenant_a,
                    mission_id=episode.mission_id,
                    evidence_type="execution_trace",
                    evidence_source="public_evidence_contract",
                    summary="Caller-forged Outcome",
                    structured_payload=canonical_outcome.structured_payload,
                    provenance_metadata={"action_name": "analysis.evaluate_outcome"},
                ),
                EvidenceRecord(
                    id=forged_execution_id,
                    tenant_id=tenant_a,
                    mission_id=episode.mission_id,
                    evidence_type="execution_trace",
                    evidence_source="public_evidence_contract",
                    summary="Caller-forged execution",
                    structured_payload=canonical_execution.structured_payload,
                    provenance_metadata={"action_name": "sales.recommend_next_action"},
                ),
            ]
        )
        setup.commit()

    forged_requests = (
        {**request, "recommendation_evidence_id": str(forged_recommendation_id)},
        {**request, "outcome_evaluation_evidence_id": str(forged_outcome_id)},
        {**request, "execution_evidence_ids": [str(forged_execution_id)]},
    )
    for forged_request in forged_requests:
        with pytest.raises(CanonicalToolEvidenceError, match="materialization reference"):
            registry.invoke(ToolInvocation(action=MATERIALIZATION_ACTION, input=forged_request), context)
