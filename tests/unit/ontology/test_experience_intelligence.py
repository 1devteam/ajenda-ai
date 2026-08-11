from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import permutations
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.services.ontology.decision_feedback import (
    ConfidenceCalibrationAssessment,
    ConfidenceCalibrationStatus,
    ConsequenceInventory,
    DecisionEffectivenessEvaluation,
    DecisionEffectivenessStatus,
    DecisionLearningSignal,
    DecisionQualityAssessment,
    DecisionQualityStatus,
    EffectivenessDimensions,
    ExecutionFidelity,
    LearningSignalStrength,
)
from backend.services.ontology.experience_intelligence import (
    ComparabilityStatus,
    ExperienceEpisodeInput,
    ExperiencePatternCandidate,
    IndependenceStatus,
    RecurrenceStrength,
    evaluate_experience_set,
)
from backend.services.ontology.observation_attribution import ObservationTimeProvenance
from backend.services.ontology.outcome import AttributionAssessment
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import (
    ActionRuntimeContext,
    SideEffectClass,
    ToolInvocation,
)


def signal(
    i: int,
    *,
    subject_type=BusinessObjectType.OPPORTUNITY,
    subject_id=None,
    subject_refs=None,
    goal="goal-a",
    status=DecisionEffectivenessStatus.EFFECTIVE,
    attr=AttributionAssessment.SUPPORTED_CONTRIBUTION,
    signal_id=None,
    decision_id=None,
    evidence=None,
    fidelity=ExecutionFidelity.EXECUTED_AS_RECOMMENDED,
    strength=LearningSignalStrength.SUPPORTED,
    scope=("smb",),
    invalidation=(),
) -> DecisionLearningSignal:
    now = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)
    refs = subject_refs or [
        BusinessObjectRef(object_type=subject_type, object_id=subject_id or f"obj-{i}")
    ]
    return DecisionLearningSignal(
        signal_id=signal_id or f"sig-{i}",
        decision_id=decision_id or f"dec-{i}",
        subject_refs=refs,
        goal_id=goal,
        decision_quality=DecisionQualityAssessment(
            status=DecisionQualityStatus.WELL_SUPPORTED,
            confidence=0.9,
            confidence_consistent_with_evidence=True,
        ),
        execution_fidelity=fidelity,
        effectiveness=DecisionEffectivenessEvaluation(
            status=status,
            confidence=0.8,
            dimensions=EffectivenessDimensions(
                execution_fidelity=fidelity, attribution_strength=attr
            ),
        ),
        confidence_calibration=ConfidenceCalibrationAssessment(
            status=ConfidenceCalibrationStatus.WELL_CALIBRATED, original_confidence=0.8
        ),
        consequences=ConsequenceInventory(),
        attribution_strength=attr,
        supporting_evidence_ids=evidence or [f"ev-{i}"],
        signal_strength=strength,
        evaluated_at=now,
        effective_dimensions=["conversion"],
        scope_conditions=list(scope),
        invalidation_conditions=list(invalidation),
    )


def ep(i: int, **kw) -> ExperienceEpisodeInput:
    rec = kw.pop("recommendation_class", "discount_offer")
    provenance = kw.pop("provenance", ObservationTimeProvenance.SOURCE_VERIFIED)
    objectives = kw.pop("objective_dimensions", ("increase_conversion",))
    lineage = kw.pop("lineage_ids", ())
    attribution_evidence_ids = kw.pop("attribution_evidence_ids", ())
    return ExperienceEpisodeInput(
        episode_id=f"ep-{i}",
        signal=signal(i, **kw),
        recommendation_class=rec,
        objective_dimensions=objectives,
        attribution_evidence_ids=attribution_evidence_ids,
        observation_time_provenance=provenance,
        lineage_ids=lineage,
    )


def recurrence_dump(episodes: list[ExperienceEpisodeInput]) -> dict:
    return evaluate_experience_set(episodes).model_dump(
        mode="json", exclude={"comparisons", "signatures"}
    )


def test_same_subject_type_different_instances_comparable_supported_and_permutation_invariant() -> (
    None
):
    episodes = [ep(1), ep(2), ep(3)]
    baseline = recurrence_dump(episodes)
    for ordered in permutations(episodes):
        assert recurrence_dump(list(ordered)) == baseline
    result = evaluate_experience_set(episodes)
    assert result.comparisons[0].comparability == ComparabilityStatus.COMPARABLE
    assert result.comparisons[0].independence == IndependenceStatus.INDEPENDENT
    assert len(result.pattern_candidates) == 1
    assert (
        result.pattern_candidates[0].recurrence.strength == RecurrenceStrength.SUPPORTED
    )
    assert result.pattern_candidates[0].recurrence.independent_support_count == 3


def test_set_like_signature_fields_are_order_invariant() -> None:
    refs_a = [
        BusinessObjectRef(object_type=BusinessObjectType.ACCOUNT, object_id="acct-1"),
        BusinessObjectRef(
            object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-1"
        ),
    ]
    refs_b = list(reversed(refs_a))
    result = evaluate_experience_set(
        [
            ep(
                1,
                subject_refs=refs_a,
                scope=("region=west", "segment=smb"),
                evidence=["b", "a"],
            ),
            ep(
                2,
                subject_refs=refs_b,
                scope=("segment=smb", "region=west"),
                evidence=["c"],
            ),
        ]
    )
    assert (
        result.signatures[0].semantic_subject_types
        == result.signatures[1].semantic_subject_types
    )
    assert (
        result.signatures[0].scope_conditions == result.signatures[1].scope_conditions
    )
    assert result.pattern_candidates[0].partition_key.startswith(
        "experience-partition-v1:"
    )


def test_opaque_evidence_and_lineage_ids_preserve_case_identity() -> None:
    result = evaluate_experience_set(
        [
            ep(1, evidence=["Evidence-A"], lineage_ids=("Lineage-A",)),
            ep(2, evidence=["evidence-a"], lineage_ids=("lineage-a",)),
        ]
    )
    assert result.signatures[0].supporting_evidence_ids == ("Evidence-A",)
    assert result.signatures[1].supporting_evidence_ids == ("evidence-a",)
    assert result.signatures[0].lineage_ids == ("Lineage-A",)
    assert result.signatures[1].lineage_ids == ("lineage-a",)
    assert result.comparisons[0].independence == IndependenceStatus.INDEPENDENT


def test_heterogeneous_singleton_partitions_do_not_emit_candidates() -> None:
    result = evaluate_experience_set(
        [
            ep(1),
            ep(2, subject_type=BusinessObjectType.ACCOUNT),
            ep(3, recommendation_class="email_nudge"),
        ]
    )
    assert any(
        c.comparability == ComparabilityStatus.INCOMPATIBLE for c in result.comparisons
    )
    assert result.pattern_candidates == ()
    assert len(result.partition_explanations) == 3


def test_same_exact_subject_instance_surfaces_partial_dependence_and_is_order_invariant() -> (
    None
):
    episodes = [
        ep(1, subject_id="same"),
        ep(2, subject_id="same"),
        ep(3, subject_id="same"),
    ]
    baseline = recurrence_dump(episodes)
    for ordered in permutations(episodes):
        assert recurrence_dump(list(ordered)) == baseline
    candidate = evaluate_experience_set(episodes).pattern_candidates[0]
    assert candidate.recurrence.independence == IndependenceStatus.PARTIALLY_INDEPENDENT
    assert candidate.recurrence.independent_support_count == 0
    assert candidate.recurrence.strength == RecurrenceStrength.WEAK


def test_goal_semantics_fail_closed_without_owned_goal_identity() -> None:
    different = evaluate_experience_set([ep(1, goal="goal-a"), ep(2, goal="goal-b")])
    assert different.comparisons[0].comparability == ComparabilityStatus.INCOMPATIBLE
    assert different.pattern_candidates == ()
    missing = evaluate_experience_set([ep(1, goal=None), ep(2, goal=None)])
    assert (
        missing.comparisons[0].comparability == ComparabilityStatus.INSUFFICIENT_CONTEXT
    )
    assert missing.unclassified_episode_ids == ("ep-1", "ep-2")
    assert missing.pattern_candidates == ()


def test_missing_or_unknown_recommendation_class_is_unclassified_not_unknown_partition() -> (
    None
):
    result = evaluate_experience_set(
        [ep(1, recommendation_class=None), ep(2, recommendation_class="unknown"), ep(3)]
    )
    assert result.unclassified_episode_ids == ("ep-1", "ep-2")
    assert result.pattern_candidates == ()
    assert "unknown" not in "|".join(result.partition_explanations)


def test_duplicate_episode_id_fails_closed() -> None:
    episode = ep(1)
    duplicate = episode.model_copy(update={"signal": signal(2)})
    with pytest.raises(ValueError, match="duplicate episode_id"):
        evaluate_experience_set([episode, duplicate])


def test_duplicate_artifacts_and_shared_lineage_are_order_invariant_dependence() -> (
    None
):
    episodes = [
        ep(1, signal_id="same-signal"),
        ep(2, signal_id="same-signal"),
        ep(3, decision_id="same-decision"),
        ep(4, decision_id="same-decision"),
        ep(5, lineage_ids=("lineage-a",)),
        ep(6, lineage_ids=("lineage-a",)),
        ep(7, evidence=["shared"]),
        ep(8, evidence=["shared"]),
    ]
    baseline = recurrence_dump(episodes)
    for ordered in (
        episodes,
        list(reversed(episodes)),
        [episodes[i] for i in (7, 0, 6, 1, 5, 2, 4, 3)],
    ):
        assert recurrence_dump(ordered) == baseline
    candidate = evaluate_experience_set(episodes).pattern_candidates[0]
    assert candidate.recurrence.independence in {
        IndependenceStatus.DEPENDENT,
        IndependenceStatus.PARTIALLY_INDEPENDENT,
    }
    assert candidate.recurrence.dependent_support_count > 0
    assert candidate.recurrence.strength != RecurrenceStrength.SUPPORTED


def test_same_decision_positive_and_negative_is_ambiguous_not_contested() -> None:
    result = evaluate_experience_set(
        [
            ep(1, decision_id="same"),
            ep(2, decision_id="same", status=DecisionEffectivenessStatus.INEFFECTIVE),
        ]
    )
    assert result.pattern_candidates == ()
    assert result.partition_explanations


def test_independent_positive_and_negative_is_contested() -> None:
    result = evaluate_experience_set(
        [ep(1), ep(2, status=DecisionEffectivenessStatus.INEFFECTIVE)]
    )
    assert (
        result.pattern_candidates[0].recurrence.strength == RecurrenceStrength.CONTESTED
    )


def test_weak_attribution_and_caller_asserted_provenance_do_not_create_supported() -> (
    None
):
    temporal = evaluate_experience_set(
        [
            ep(1, attr=AttributionAssessment.SUPPORTED_CONTRIBUTION),
            ep(2, attr=AttributionAssessment.SUPPORTED_CONTRIBUTION),
            ep(3, attr=AttributionAssessment.TEMPORAL_ASSOCIATION),
        ]
    )
    assert (
        temporal.pattern_candidates[0].recurrence.strength
        != RecurrenceStrength.SUPPORTED
    )
    asserted = evaluate_experience_set(
        [
            ep(1, provenance=ObservationTimeProvenance.CALLER_ASSERTED),
            ep(2, provenance=ObservationTimeProvenance.CALLER_ASSERTED),
            ep(3, provenance=ObservationTimeProvenance.CALLER_ASSERTED),
        ]
    )
    assert (
        asserted.pattern_candidates[0].recurrence.strength
        != RecurrenceStrength.SUPPORTED
    )
    assert asserted.pattern_candidates[0].recurrence.limited_support_count == 3
    assert (
        asserted.pattern_candidates[0].recurrence.evidence_limitation
        == "limited_evidence_present"
    )


def test_unrelated_weak_episode_does_not_downgrade_three_strong_supported_observations() -> (
    None
):
    result = evaluate_experience_set(
        [ep(1), ep(2), ep(3), ep(4, attr=AttributionAssessment.TEMPORAL_ASSOCIATION)]
    )
    candidate = result.pattern_candidates[0]
    assert candidate.recurrence.strength == RecurrenceStrength.SUPPORTED
    assert candidate.recurrence.independent_support_count == 3
    assert candidate.recurrence.limited_support_count == 1


def test_execution_fidelity_controls_recurrence_eligibility_and_exclusions() -> None:
    result = evaluate_experience_set(
        [
            ep(1),
            ep(2),
            ep(
                3,
                fidelity=ExecutionFidelity.NOT_EXECUTED,
                status=DecisionEffectivenessStatus.NOT_EXECUTED,
            ),
            ep(4, fidelity=ExecutionFidelity.EXECUTION_UNKNOWN),
            ep(5, fidelity=ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION),
            ep(6, fidelity=ExecutionFidelity.PARTIALLY_EXECUTED),
        ]
    )
    candidate = result.pattern_candidates[0]
    assert set(result.excluded_episode_ids) == {"ep-3", "ep-4", "ep-5"}
    assert "ep-3" not in candidate.contradicting_episode_ids
    assert candidate.recurrence.limited_support_count == 1


def test_weak_and_candidate_learning_signals_cannot_manufacture_supported() -> None:
    weak = evaluate_experience_set(
        [
            ep(1, strength=LearningSignalStrength.WEAK),
            ep(2, strength=LearningSignalStrength.WEAK),
            ep(3, strength=LearningSignalStrength.WEAK),
        ]
    )
    assert (
        weak.pattern_candidates[0].recurrence.strength != RecurrenceStrength.SUPPORTED
    )
    candidate = evaluate_experience_set(
        [
            ep(1, strength=LearningSignalStrength.CANDIDATE),
            ep(2, strength=LearningSignalStrength.CANDIDATE),
            ep(3, strength=LearningSignalStrength.CANDIDATE),
        ]
    )
    assert (
        candidate.pattern_candidates[0].recurrence.strength
        != RecurrenceStrength.SUPPORTED
    )


def test_scope_partitions_before_recurrence_and_invalidation_excludes() -> None:
    scoped = evaluate_experience_set(
        [ep(1, scope=("discovery",)), ep(2, scope=("procurement",)), ep(3, scope=())]
    )
    assert scoped.pattern_candidates == ()
    invalidated = evaluate_experience_set(
        [
            ep(1, scope=("smb",), invalidation=("smb",)),
            ep(2, scope=("smb",)),
            ep(3, scope=("smb",)),
        ]
    )
    assert invalidated.excluded_episode_ids == ("ep-1",)
    assert invalidated.pattern_candidates[0].excluded_episode_ids == ("ep-1",)


def test_counterexamples_are_partition_local_and_repeated_independent_contradictions_invalidate() -> (
    None
):
    invalidated = evaluate_experience_set(
        [
            ep(1, status=DecisionEffectivenessStatus.INEFFECTIVE),
            ep(2, status=DecisionEffectivenessStatus.COUNTERPRODUCTIVE),
        ]
    )
    assert (
        invalidated.pattern_candidates[0].recurrence.strength
        == RecurrenceStrength.INVALIDATED
    )
    mixed = evaluate_experience_set(
        [
            ep(1),
            ep(2),
            ep(
                3,
                subject_type=BusinessObjectType.ACCOUNT,
                status=DecisionEffectivenessStatus.INEFFECTIVE,
            ),
        ]
    )
    assert len(mixed.pattern_candidates) == 1
    assert mixed.pattern_candidates[0].contradicting_episode_ids == ()


def test_limited_contradictions_cannot_manufacture_invalidation() -> None:
    limited_only = evaluate_experience_set(
        [
            ep(
                1,
                status=DecisionEffectivenessStatus.INEFFECTIVE,
                provenance=ObservationTimeProvenance.CALLER_ASSERTED,
            ),
            ep(
                2,
                status=DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
                provenance=ObservationTimeProvenance.CALLER_ASSERTED,
            ),
        ]
    ).pattern_candidates[0]
    assert limited_only.recurrence.strength == RecurrenceStrength.WEAK
    assert limited_only.recurrence.strong_independent_contradiction_count == 0
    assert limited_only.recurrence.limited_contradiction_count == 2
    assert limited_only.recurrence.evidence_limitation == "limited_evidence_present"

    strong_with_limited_counterexamples = evaluate_experience_set(
        [
            ep(1),
            ep(2),
            ep(3),
            ep(
                4,
                status=DecisionEffectivenessStatus.INEFFECTIVE,
                provenance=ObservationTimeProvenance.CALLER_ASSERTED,
            ),
            ep(
                5,
                status=DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
                provenance=ObservationTimeProvenance.CALLER_ASSERTED,
            ),
        ]
    ).pattern_candidates[0]
    assert (
        strong_with_limited_counterexamples.recurrence.strength
        == RecurrenceStrength.SUPPORTED
    )
    assert strong_with_limited_counterexamples.recurrence.independent_support_count == 3
    assert (
        strong_with_limited_counterexamples.recurrence.limited_contradiction_count == 2
    )


def test_strong_independent_contradictions_retain_invalidation_authority() -> None:
    candidate = evaluate_experience_set(
        [
            ep(1, status=DecisionEffectivenessStatus.INEFFECTIVE),
            ep(2, status=DecisionEffectivenessStatus.COUNTERPRODUCTIVE),
        ]
    ).pattern_candidates[0]
    assert candidate.recurrence.strength == RecurrenceStrength.INVALIDATED
    assert candidate.recurrence.strong_independent_contradiction_count == 2
    assert candidate.recurrence.limited_contradiction_count == 0


def test_candidate_objective_context_is_common_only_and_order_invariant() -> None:
    common = evaluate_experience_set(
        [
            ep(1, objective_dimensions=("increase_conversion",)),
            ep(2, objective_dimensions=("increase_conversion",)),
        ]
    ).pattern_candidates[0]
    assert common.objective_dimensions == ("increase_conversion",)

    divergent_episodes = [
        ep(1, objective_dimensions=("increase_conversion",)),
        ep(2, objective_dimensions=("reduce_churn",)),
    ]
    divergent = evaluate_experience_set(divergent_episodes).pattern_candidates[0]
    reversed_divergent = evaluate_experience_set(
        list(reversed(divergent_episodes))
    ).pattern_candidates[0]
    assert divergent.objective_dimensions == ()
    assert "caller_objective_context_diverged" in divergent.explanation_codes
    assert divergent.model_dump(mode="json") == reversed_divergent.model_dump(
        mode="json"
    )


def test_heterogeneous_groups_with_enough_observations_emit_multiple_stable_candidates() -> (
    None
):
    episodes = [
        ep(1),
        ep(2),
        ep(3, recommendation_class="email_nudge"),
        ep(4, recommendation_class="email_nudge"),
    ]
    result = evaluate_experience_set(episodes)
    reversed_result = evaluate_experience_set(list(reversed(episodes)))
    assert len(result.pattern_candidates) == 2
    assert result.model_dump(
        mode="json", exclude={"comparisons", "signatures"}
    ) == reversed_result.model_dump(mode="json", exclude={"comparisons", "signatures"})
    assert [c.candidate_id for c in result.pattern_candidates] == [
        c.candidate_id for c in reversed_result.pattern_candidates
    ]


def test_candidate_safety_flags_are_immutable_and_not_overridable() -> None:
    result = evaluate_experience_set([ep(1), ep(2)])
    candidate = result.pattern_candidates[0]
    assert candidate.is_knowledge is False and candidate.is_policy is False
    with pytest.raises(ValidationError):
        ExperiencePatternCandidate.model_validate(
            {**candidate.model_dump(), "is_knowledge": True}
        )
    with pytest.raises(ValidationError):
        candidate.is_policy = True  # type: ignore[misc]


def test_action_registry_experience_actions_have_evidence_and_no_side_effects() -> None:
    registry = get_default_action_registry(rebuild=True)
    ctx = ActionRuntimeContext(
        tenant_id="t", task_id=uuid4(), worker_id="w", lease_id="l"
    )
    payload = {
        "episodes": [ep(1).model_dump(mode="json"), ep(2).model_dump(mode="json")]
    }
    for action in (
        "analysis.compare_experiences",
        "analysis.assess_experience_recurrence",
    ):
        definition = registry.get(action)
        assert definition.side_effect_class == SideEffectClass.NONE
        result = registry.invoke(ToolInvocation(action=action, input=payload), ctx)
        assert result.side_effect_class == SideEffectClass.NONE
        assert (
            result.evidence
            and result.evidence[0].evidence_type == "action_result_evidence"
        )
        if action == "analysis.assess_experience_recurrence":
            assert result.output["pattern_candidates"]


def test_compare_action_reports_partitions_separately_from_candidates() -> None:
    registry = get_default_action_registry(rebuild=True)
    ctx = ActionRuntimeContext(
        tenant_id="t", task_id=uuid4(), worker_id="w", lease_id="l"
    )
    episodes = [
        ep(1),
        ep(2, subject_type=BusinessObjectType.ACCOUNT),
        ep(3, recommendation_class="email_nudge"),
    ]
    result = registry.invoke(
        ToolInvocation(
            action="analysis.compare_experiences",
            input={
                "episodes": [episode.model_dump(mode="json") for episode in episodes]
            },
        ),
        ctx,
    )
    assert "across 3 semantic partitions; candidates=0" in result.summary
