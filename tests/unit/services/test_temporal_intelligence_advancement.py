from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from backend.domain.evidence import EvidenceRecord
from backend.services.decision_episode_materialization import DecisionEpisodeMaterializationResult
from backend.services.ontology.decision_feedback import DecisionEpisodeReference
from backend.services.ontology.outcome import AttributionAssessment, OutcomeEvaluation, OutcomeStatus
from backend.services.temporal_intelligence_advancement import (
    TemporalAdvancementState,
    TemporalIntelligenceAdvancementService,
    TemporalTransition,
    _task_id,
)

TENANT = "tenant-a"
MISSION = uuid.uuid4()


def _record(*, action: str, role: str | None = None, payload: dict | None = None) -> EvidenceRecord:
    provenance = {"action_name": action}
    if role:
        provenance["evidence_role"] = role
    return EvidenceRecord(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        mission_id=MISSION,
        evidence_type="execution_trace",
        evidence_source="test",
        summary="test",
        structured_payload=payload or {},
        provenance_metadata=provenance,
        confidence=0.8,
    )


def _outcome(*, execution_ids: list[str]) -> EvidenceRecord:
    evaluated = datetime(2026, 8, 15, 12, tzinfo=UTC)
    payload = OutcomeEvaluation(
        outcome_evaluation_id="outcome-1",
        status=OutcomeStatus.ACHIEVED,
        attribution=AttributionAssessment.NOT_ASSESSED,
        confidence=0.8,
        evaluated_at=evaluated,
    ).model_dump(mode="json")
    if execution_ids:
        payload["attribution_evidence"] = {
            "executed_at": evaluated.isoformat(),
            "execution_evidence_ids": execution_ids,
            "expected_change_dimensions": [],
            "observed_change_dimensions": [],
            "competing_explanations": [],
            "conflicting_evidence_ids": [],
            "confidence": 0.8,
            "observation_timing": payload["observation_timing"],
            "ordering": "unknown",
            "resulting_attribution": "not_assessed",
            "explanation_codes": [],
        }
    return _record(action="analysis.evaluate_outcome", payload=payload)


def test_transition_task_identity_is_stable_and_tenant_scoped() -> None:
    source = uuid.uuid4()
    transition = TemporalTransition.OUTCOME_TO_DECISION_EPISODE

    assert _task_id(transition, TENANT, source) == _task_id(transition, TENANT, source)
    assert _task_id(transition, TENANT, source) != _task_id(transition, "tenant-b", source)


def test_outcome_without_execution_ancestry_is_not_eligible() -> None:
    outcome = _outcome(execution_ids=[])
    recommendation = _record(action="decision.recommend_next_action", role="decision_recommendation_result")
    service = TemporalIntelligenceAdvancementService(session=MagicMock(), queue=MagicMock())

    with (
        patch("backend.services.temporal_intelligence_advancement.require_canonical_tool_action_evidence"),
        patch.object(service, "_unique_recommendation", return_value=recommendation),
    ):
        result = service._advance_outcome(tenant_id=TENANT, outcome_record=outcome)

    assert result.state == TemporalAdvancementState.NOT_ELIGIBLE
    assert "execution evidence" in result.reason


def test_forged_outcome_is_blocked_before_transition() -> None:
    outcome = _outcome(execution_ids=[str(uuid.uuid4())])
    service = TemporalIntelligenceAdvancementService(session=MagicMock(), queue=MagicMock())

    with patch(
        "backend.services.temporal_intelligence_advancement.require_canonical_tool_action_evidence",
        side_effect=ValueError("not canonical"),
    ):
        result = service._advance_outcome(tenant_id=TENANT, outcome_record=outcome)

    assert result.state == TemporalAdvancementState.BLOCKED
    assert result.reason == "not canonical"


def test_valid_owner_preflight_delegates_to_canonical_materialization() -> None:
    execution_id = uuid.uuid4()
    outcome = _outcome(execution_ids=[str(execution_id)])
    recommendation = _record(action="decision.recommend_next_action", role="decision_recommendation_result")
    service = TemporalIntelligenceAdvancementService(session=MagicMock(), queue=MagicMock())
    episode = DecisionEpisodeReference(
        episode_id="episode-1",
        decision_id="decision-1",
        recommendation_evidence_id=str(recommendation.id),
        mission_id=str(MISSION),
        recommendation_execution_task_id=str(uuid.uuid4()),
        outcome_evaluation_evidence_id=str(outcome.id),
        execution_evidence_ids=(str(execution_id),),
    )
    materialized = MagicMock(spec=DecisionEpisodeMaterializationResult)
    materialized.episode_reference = episode
    parsed_outcome = MagicMock()
    parsed_outcome.attribution_evidence.execution_evidence_ids = [str(execution_id)]

    with (
        patch("backend.services.temporal_intelligence_advancement.require_canonical_tool_action_evidence"),
        patch(
            "backend.services.temporal_intelligence_advancement.OutcomeEvaluation.model_validate",
            return_value=parsed_outcome,
        ),
        patch.object(service, "_unique_recommendation", return_value=recommendation),
        patch(
            "backend.services.temporal_intelligence_advancement.DecisionEpisodeMaterializationService.materialize",
            return_value=materialized,
        ) as owner,
        patch.object(service, "_existing_learning_signal", return_value=None),
        patch.object(service, "_schedule") as schedule,
    ):
        schedule.return_value = service._result(
            TemporalTransition.OUTCOME_TO_DECISION_EPISODE,
            TemporalAdvancementState.ADVANCED,
            outcome.id,
            "queued",
        )
        result = service._advance_outcome(tenant_id=TENANT, outcome_record=outcome)

    assert result.state == TemporalAdvancementState.ADVANCED
    request = owner.call_args.kwargs["request"]
    assert request.recommendation_evidence_id == recommendation.id
    assert request.execution_evidence_ids == [execution_id]
    schedule.assert_called_once()


def test_existing_episode_is_classified_as_already_advanced() -> None:
    execution_id = uuid.uuid4()
    outcome = _outcome(execution_ids=[str(execution_id)])
    recommendation = _record(action="decision.recommend_next_action", role="decision_recommendation_result")
    service = TemporalIntelligenceAdvancementService(session=MagicMock(), queue=MagicMock())
    materialized = MagicMock()
    materialized.episode_reference.episode_id = "episode-1"
    existing = _record(action="analysis.materialize_decision_learning_signal", role="decision_learning_signal")
    parsed_outcome = MagicMock()
    parsed_outcome.attribution_evidence.execution_evidence_ids = [str(execution_id)]

    with (
        patch("backend.services.temporal_intelligence_advancement.require_canonical_tool_action_evidence"),
        patch(
            "backend.services.temporal_intelligence_advancement.OutcomeEvaluation.model_validate",
            return_value=parsed_outcome,
        ),
        patch.object(service, "_unique_recommendation", return_value=recommendation),
        patch(
            "backend.services.temporal_intelligence_advancement.DecisionEpisodeMaterializationService.materialize",
            return_value=materialized,
        ),
        patch.object(service, "_existing_learning_signal", return_value=existing),
    ):
        result = service._advance_outcome(tenant_id=TENANT, outcome_record=outcome)

    assert result.state == TemporalAdvancementState.ALREADY_ADVANCED


def test_unexpected_owner_failure_is_retryable_failed_state() -> None:
    execution_id = uuid.uuid4()
    outcome = _outcome(execution_ids=[str(execution_id)])
    recommendation = _record(action="decision.recommend_next_action", role="decision_recommendation_result")
    service = TemporalIntelligenceAdvancementService(session=MagicMock(), queue=MagicMock())
    parsed_outcome = MagicMock()
    parsed_outcome.attribution_evidence.execution_evidence_ids = [str(execution_id)]

    with (
        patch("backend.services.temporal_intelligence_advancement.require_canonical_tool_action_evidence"),
        patch(
            "backend.services.temporal_intelligence_advancement.OutcomeEvaluation.model_validate",
            return_value=parsed_outcome,
        ),
        patch.object(service, "_unique_recommendation", return_value=recommendation),
        patch(
            "backend.services.temporal_intelligence_advancement.DecisionEpisodeMaterializationService.materialize",
            side_effect=RuntimeError("repository unavailable"),
        ),
    ):
        result = service._advance_outcome(tenant_id=TENANT, outcome_record=outcome)

    assert result.state == TemporalAdvancementState.FAILED
    assert result.reason == "repository unavailable"


def test_forged_learning_signal_is_blocked_before_experience() -> None:
    signal = _record(
        action="analysis.materialize_decision_learning_signal",
        role="decision_learning_signal",
    )
    service = TemporalIntelligenceAdvancementService(session=MagicMock(), queue=MagicMock())

    with patch(
        "backend.services.temporal_intelligence_advancement.require_canonical_tool_action_evidence",
        side_effect=ValueError("not canonical"),
    ):
        result = service._advance_learning_signal(tenant_id=TENANT, signal_record=signal)

    assert result.state == TemporalAdvancementState.BLOCKED
    assert result.reason == "not canonical"
