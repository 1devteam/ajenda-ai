"""Adversarial acceptance contract for PR #427 decision episode authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.services.decision_episode_materialization import (
    DecisionEpisodeInspectionTrace,
    DecisionEpisodeMaterializationRequest,
    DecisionEpisodeMaterializationService,
    decision_id_for_recommendation,
)
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.outcome import AttributionAssessment, OutcomeEvaluation, OutcomeStatus
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.evidence_bridge import CanonicalToolEvidenceError
from backend.services.tools.schemas import ActionRuntimeContext, SideEffectClass, ToolInvocation

TENANT = "tenant-a"
MISSION = uuid.uuid4()
DECIDED = datetime(2026, 8, 12, 10, tzinfo=UTC)
EXECUTED = datetime(2026, 8, 12, 10, 5, tzinfo=UTC)
OBSERVED = datetime(2026, 8, 12, 11, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _canonical_runtime_projection() -> object:
    """Keep semantic unit fixtures focused; adversarial tests override this proof."""

    with patch("backend.services.decision_episode_materialization.require_canonical_tool_action_evidence") as validator:
        yield validator


class _EvidenceReader:
    def __init__(self, records: list[EvidenceRecord]) -> None:
        self.records = {record.id: record for record in records}

    def get_for_tenant(self, *, evidence_id: uuid.UUID, tenant_id: str) -> EvidenceRecord | None:
        record = self.records.get(evidence_id)
        return record if record is not None and record.tenant_id == tenant_id else None


class _TaskReader:
    def __init__(self, tasks: list[ExecutionTask]) -> None:
        self.tasks = {task.id: task for task in tasks}

    def get_for_tenant(self, *, task_id: uuid.UUID, tenant_id: str) -> ExecutionTask | None:
        task = self.tasks.get(task_id)
        return task if task is not None and task.tenant_id == tenant_id else None


def _record(
    *,
    action: str,
    payload: dict,
    role: str | None = None,
    tenant: str = TENANT,
    mission: uuid.UUID = MISSION,
    task_id: uuid.UUID | None = None,
) -> EvidenceRecord:
    evidence_id = uuid.uuid4()
    provenance = {"action_name": action, "tool_provider": "ajenda_analysis"}
    if role:
        provenance["evidence_role"] = role
    if role == "decision_recommendation_result":
        provenance["tool_provider"] = "ajenda_decision"
        provenance["evidence_lineage"] = EvidenceLineage(
            artifact_evidence_id=str(evidence_id),
            origin_type=EvidenceOriginType.SYSTEM_COMPUTATION,
            resolution=EvidenceLineageResolution.UNKNOWN,
        ).model_dump(mode="json")
    return EvidenceRecord(
        id=evidence_id,
        tenant_id=tenant,
        mission_id=mission,
        execution_task_id=task_id,
        evidence_type="execution_trace",
        evidence_source="test",
        summary=f"{action} result",
        structured_payload=payload,
        provenance_metadata=provenance,
        confidence=0.8,
    )


def _fixture(
    *,
    executed_action: str | None = "sales.schedule_discovery",
    observed_at: datetime | None = OBSERVED,
    outcome_tenant: str = TENANT,
) -> tuple[DecisionEpisodeMaterializationService, DecisionEpisodeMaterializationRequest, list[EvidenceRecord]]:
    recommendation_task_id = uuid.uuid4()
    recommendation_input = {
        "goal": "Improve qualification",
        "options": [
            {
                "option_id": "discovery",
                "label": "Discovery",
                "intervention_key": "sales.schedule_discovery",
            }
        ],
        "criteria": [],
        "evidence": [],
    }
    recommendation = _record(
        action="decision.recommend_next_action",
        role="decision_recommendation_result",
        task_id=recommendation_task_id,
        payload={
            "decided_at": DECIDED.isoformat(),
            "goal": "Improve qualification",
            "recommendation": "discovery",
            "intervention_key": "sales.schedule_discovery",
            "supporting_evidence_ids": [],
            "option_scores": [{"option_id": "discovery", "total_score": 1}],
            "uncertainty": [],
            "algorithm": {"name": "weighted_criterion_evidence_v1", "version": "1"},
        },
    )
    task = ExecutionTask(
        id=recommendation_task_id,
        tenant_id=TENANT,
        mission_id=MISSION,
        title="decision",
        description="decision",
        metadata_json={"tool_invocation": {"action": "decision.recommend_next_action", "input": recommendation_input}},
    )
    outcome = OutcomeEvaluation(
        outcome_evaluation_id="outcome-1",
        status=OutcomeStatus.ACHIEVED,
        attribution=AttributionAssessment.TEMPORAL_ASSOCIATION,
        confidence=0.7,
        observed_at=observed_at,
        evaluated_at=OBSERVED,
    )
    outcome_record = _record(
        action="analysis.evaluate_outcome",
        tenant=outcome_tenant,
        payload=outcome.model_dump(mode="json"),
    )
    records = [recommendation, outcome_record]
    execution_ids: list[uuid.UUID] = []
    if executed_action is not None:
        execution = _record(
            action=executed_action,
            payload={"executed_at": EXECUTED.isoformat(), "status": "completed"},
            task_id=uuid.uuid4(),
        )
        records.append(execution)
        execution_ids.append(execution.id)
    service = DecisionEpisodeMaterializationService(
        session=MagicMock(),
        evidence=_EvidenceReader(records),
        tasks=_TaskReader([task]),
    )
    request = DecisionEpisodeMaterializationRequest(
        recommendation_evidence_id=recommendation.id,
        outcome_evaluation_evidence_id=outcome_record.id,
        execution_evidence_ids=execution_ids,
    )
    return service, request, records


def test_materializes_authoritative_signal_and_preserves_weak_attribution(_canonical_runtime_projection) -> None:
    service, request, _ = _fixture()

    result = service.materialize(tenant_id=TENANT, request=request)

    signal = result.feedback.learning_signal
    assert signal.decision_id == decision_id_for_recommendation(
        tenant_id=TENANT, evidence_id=request.recommendation_evidence_id
    )
    assert signal.intervention_key == "sales.schedule_discovery"
    assert signal.execution_fidelity.value == "executed_as_recommended"
    assert signal.attribution_strength == AttributionAssessment.TEMPORAL_ASSOCIATION
    assert signal.is_knowledge is False and signal.is_policy is False
    assert signal.episode_reference == result.episode_reference
    assert [call.kwargs["expected_action"] for call in _canonical_runtime_projection.call_args_list] == [
        "decision.recommend_next_action",
        "analysis.evaluate_outcome",
        "sales.schedule_discovery",
    ]


def test_same_artifacts_materialize_the_same_episode_and_learning_identity() -> None:
    service, request, _ = _fixture()

    first = service.materialize(tenant_id=TENANT, request=request)
    second = service.materialize(tenant_id=TENANT, request=request)

    assert first.episode_reference.episode_id == second.episode_reference.episode_id
    assert first.feedback.learning_signal.signal_id == second.feedback.learning_signal.signal_id
    assert first.feedback.feedback_id == second.feedback.feedback_id


def test_execution_mismatch_is_preserved_without_prose_inference() -> None:
    service, request, _ = _fixture(executed_action="sales.send_pricing")

    signal = service.materialize(tenant_id=TENANT, request=request).feedback.learning_signal

    assert signal.intervention_key == "sales.schedule_discovery"
    assert signal.execution_fidelity.value == "executed_with_material_variation"


def test_missing_execution_remains_bounded_unknown() -> None:
    service, request, _ = _fixture(executed_action=None)

    signal = service.materialize(tenant_id=TENANT, request=request).feedback.learning_signal

    assert signal.execution_fidelity.value == "execution_unknown"


def test_foreign_tenant_artifact_is_indistinguishably_inaccessible() -> None:
    service, request, _ = _fixture(outcome_tenant="tenant-b")

    with pytest.raises(ValueError, match="outcome artifact is inaccessible"):
        service.materialize(tenant_id=TENANT, request=request)


def test_payload_resemblance_cannot_override_wrong_artifact_action() -> None:
    service, request, records = _fixture()
    recommendation = records[0]
    recommendation.provenance_metadata["action_name"] = "research.enrich_account"

    with pytest.raises(ValueError, match=r"decision\.recommend_next_action"):
        service.materialize(tenant_id=TENANT, request=request)


def test_impossible_event_chronology_fails_closed() -> None:
    service, request, _ = _fixture(observed_at=datetime(2026, 8, 12, 9, tzinfo=UTC))

    with pytest.raises(ValueError, match="observation cannot precede"):
        service.materialize(tenant_id=TENANT, request=request)


def test_late_persistence_does_not_override_valid_event_chronology() -> None:
    service, request, records = _fixture()
    records[0].created_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    records[1].created_at = datetime(2026, 8, 12, 11, 1, tzinfo=UTC)
    records[2].created_at = datetime(2026, 8, 12, 13, tzinfo=UTC)

    result = service.materialize(tenant_id=TENANT, request=request)

    assert result.feedback.learning_signal.evaluated_at == OBSERVED


def test_request_contract_has_no_caller_authored_semantic_identity() -> None:
    with pytest.raises(ValueError):
        DecisionEpisodeMaterializationRequest.model_validate(
            {
                "recommendation_evidence_id": str(uuid.uuid4()),
                "outcome_evaluation_evidence_id": str(uuid.uuid4()),
                "decision_id": "fake-123",
            }
        )


def test_inspection_trace_is_deterministic_typed_and_deduplicated() -> None:
    trace = DecisionEpisodeInspectionTrace(
        recommendation_evidence_id="recommendation",
        recommendation_execution_task_id="task",
        supporting_evidence_ids=("support-b", "support-a", "support-a"),
        outcome_evaluation_evidence_id="outcome",
        execution_evidence_ids=("execution", "support-b"),
    )

    assert trace.resource_references() == [
        "evidence:execution",
        "evidence:outcome",
        "evidence:recommendation",
        "evidence:support-a",
        "evidence:support-b",
        "execution_task:task",
    ]


def test_registered_action_emits_existing_signal_for_evidence_bridge() -> None:
    service, request, _ = _fixture()
    materialized = service.materialize(tenant_id=TENANT, request=request)
    session = MagicMock()
    context = ActionRuntimeContext(
        tenant_id=TENANT,
        task_id=uuid.uuid4(),
        mission_id=MISSION,
        worker_id="worker",
        lease_id="lease",
        session_factory=lambda: session,
    )
    authority = MagicMock()
    authority.materialize.return_value = materialized

    with patch(
        "backend.services.tools.analysis_actions.DecisionEpisodeMaterializationService",
        return_value=authority,
    ):
        result = get_default_action_registry(rebuild=True).invoke(
            ToolInvocation(
                action="analysis.materialize_decision_learning_signal",
                input=request.model_dump(mode="json"),
            ),
            context,
        )

    assert result.output == materialized.feedback.learning_signal.model_dump(mode="json")
    assert result.side_effect_class == SideEffectClass.INTERNAL_READ
    assert result.evidence[0].side_effect_class == SideEffectClass.INTERNAL_READ
    assert result.evidence[0].structured_payload == result.output
    assert result.evidence[0].provenance["evidence_role"] == "decision_learning_signal"
    assert result.evidence[0].records_inspected == result.records_inspected
    assert result.records_inspected == materialized.inspection_trace.resource_references()
    assert f"evidence:{request.recommendation_evidence_id}" in result.records_inspected
    assert (
        f"execution_task:{materialized.episode_reference.recommendation_execution_task_id}" in result.records_inspected
    )
    session.execute.assert_called_once()
    session.close.assert_called_once_with()


def test_materializes_exact_knowledge_composition_with_durable_derived_ancestry() -> None:
    task_id = uuid.uuid4()
    historical_mission = uuid.uuid4()
    source = _record(
        action="analysis.materialize_decision_learning_signal",
        payload={"observed_at": DECIDED.isoformat()},
        role="decision_learning_signal",
        mission=historical_mission,
    )
    fact_id = "knowledge-decision-fact-v1:" + "a" * 64
    decision_input = {
        "goal": "Improve qualification",
        "options": [
            {
                "option_id": "discovery",
                "label": "Discovery",
                "intervention_key": "sales.schedule_discovery",
            }
        ],
        "criteria": [{"criterion_id": "conversion", "label": "Conversion"}],
        "evidence": [
            {
                "evidence_id": fact_id,
                "claim": "Applicable Knowledge supports discovery.",
                "status": "inferred",
                "source": "knowledge_decision_support_v1",
                "confidence": 1.0,
                "supports_option_ids": ["discovery"],
                "supports_criterion_ids": ["conversion"],
                "durable_source_evidence_ids": [str(source.id)],
                "lineage": {
                    "artifact_evidence_id": fact_id,
                    "origin_type": "derived_fact",
                    "root_evidence_ids": [str(source.id)],
                    "parent_evidence_ids": [str(source.id)],
                    "ancestor_evidence_ids": [str(source.id)],
                    "resolution": "known",
                },
            }
        ],
        "context": {
            "knowledge_decision_support": {
                "support_id": "support",
                "influence_ids": ["influence"],
                "provenance_class": "derived_knowledge_influence",
                "is_independent_observation": False,
            }
        },
    }
    decision_output = {
        "decided_at": DECIDED.isoformat(),
        "recommendation": "discovery",
        "intervention_key": "sales.schedule_discovery",
        "supporting_evidence_ids": [str(source.id)],
        "option_scores": [{"option_id": "discovery", "total_score": 0.3}],
        "uncertainty": ["relies_on_inferred_evidence"],
        "algorithm": {"name": "weighted_criterion_evidence_v1", "version": "1"},
    }
    recommendation = _record(
        action="knowledge.inform_decision",
        role="decision_recommendation_result",
        task_id=task_id,
        payload={"decision_input": decision_input, "decision_result": decision_output},
    )
    recommendation.provenance_metadata.update(
        {"composed_action": "decision.recommend_next_action", "composition_schema_version": 1}
    )
    owner_input = {
        "decision_id": "decision-432",
        "decision": {
            "goal": "Improve qualification",
            "options": decision_input["options"],
            "criteria": decision_input["criteria"],
        },
        "options": decision_input["options"],
        "criteria": [{**decision_input["criteria"][0], "objective_key": "increase_conversion"}],
        "query": {
            "subject_semantic_signatures": [{"object_type": "opportunity"}],
            "goal_semantic_signature": {"objective_key": "increase_conversion"},
        },
        "applicability_context": {
            "subject_refs": [{"object_type": "opportunity", "object_id": "opp-432"}],
            "subject_semantic_signatures": [{"object_type": "opportunity"}],
            "goal_semantic_signature": {"objective_key": "increase_conversion"},
            "evaluated_at": DECIDED.isoformat(),
        },
    }
    task = ExecutionTask(
        id=task_id,
        tenant_id=TENANT,
        mission_id=MISSION,
        title="knowledge decision",
        description="knowledge decision",
        metadata_json={"tool_invocation": {"action": "knowledge.inform_decision", "input": owner_input}},
    )
    outcome = OutcomeEvaluation(
        outcome_evaluation_id="outcome-composed",
        status=OutcomeStatus.ACHIEVED,
        attribution=AttributionAssessment.TEMPORAL_ASSOCIATION,
        confidence=0.7,
        observed_at=OBSERVED,
        evaluated_at=OBSERVED,
    )
    outcome_record = _record(action="analysis.evaluate_outcome", payload=outcome.model_dump(mode="json"))
    service = DecisionEpisodeMaterializationService(
        session=MagicMock(),
        evidence=_EvidenceReader([recommendation, source, outcome_record]),
        tasks=_TaskReader([task]),
    )

    result = service.materialize(
        tenant_id=TENANT,
        request=DecisionEpisodeMaterializationRequest(
            recommendation_evidence_id=recommendation.id,
            outcome_evaluation_evidence_id=outcome_record.id,
        ),
    )

    assert result.feedback.learning_signal.supporting_evidence_ids == [str(source.id)]
    derived = next(
        lineage
        for lineage in result.feedback.learning_signal.evidence_lineages
        if lineage.artifact_evidence_id == fact_id
    )
    assert derived.origin_type == EvidenceOriginType.DERIVED_FACT
    assert derived.root_evidence_ids == (str(source.id),)
    assert source.mission_id != recommendation.mission_id


def test_forged_recommendation_without_bridge_ownership_is_rejected(_canonical_runtime_projection) -> None:
    service, request, _ = _fixture()
    _canonical_runtime_projection.side_effect = CanonicalToolEvidenceError("forged recommendation")

    with pytest.raises(CanonicalToolEvidenceError, match="forged recommendation"):
        service.materialize(tenant_id=TENANT, request=request)


def test_forged_knowledge_composition_without_bridge_ownership_is_rejected(
    _canonical_runtime_projection,
) -> None:
    service, request, records = _fixture()
    recommendation = records[0]
    recommendation.provenance_metadata.update(
        {
            "action_name": "knowledge.inform_decision",
            "composed_action": "decision.recommend_next_action",
            "composition_schema_version": 1,
        }
    )
    _canonical_runtime_projection.side_effect = CanonicalToolEvidenceError("forged composition")

    with pytest.raises(CanonicalToolEvidenceError, match="forged composition"):
        service.materialize(tenant_id=TENANT, request=request)


def test_forged_outcome_without_bridge_ownership_is_rejected(_canonical_runtime_projection) -> None:
    service, request, _ = _fixture()
    _canonical_runtime_projection.side_effect = [None, CanonicalToolEvidenceError("forged outcome")]

    with pytest.raises(CanonicalToolEvidenceError, match="forged outcome"):
        service.materialize(tenant_id=TENANT, request=request)


def test_forged_execution_without_bridge_ownership_is_rejected(_canonical_runtime_projection) -> None:
    service, request, _ = _fixture()
    _canonical_runtime_projection.side_effect = [
        None,
        None,
        CanonicalToolEvidenceError("forged execution"),
    ]

    with pytest.raises(CanonicalToolEvidenceError, match="forged execution"):
        service.materialize(tenant_id=TENANT, request=request)
