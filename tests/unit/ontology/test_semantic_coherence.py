from datetime import UTC, datetime

from backend.services.ontology.commercial_state import (
    Goal,
    GoalSemanticComparisonStatus,
    Kpi,
    compare_goal_semantics,
    goal_semantic_signature,
)
from backend.services.ontology.decision_feedback import (
    ConfidenceCalibrationAssessment,
    ConfidenceCalibrationStatus,
    ConsequenceInventory,
    DecisionEffectivenessEvaluation,
    DecisionEffectivenessStatus,
    DecisionExecutionObservation,
    DecisionLearningSignal,
    DecisionQualityAssessment,
    DecisionQualityStatus,
    DecisionSnapshot,
    EffectivenessDimensions,
    ExecutionFidelity,
    LearningSignalStrength,
    evaluate_decision_feedback,
)
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
)
from backend.services.ontology.experience_intelligence import (
    ComparabilityStatus,
    ExperienceEpisodeInput,
    IndependenceStatus,
    RecurrenceStrength,
    evaluate_experience_set,
)
from backend.services.ontology.observation_attribution import AttributionAssessment, ObservationTimeProvenance
from backend.services.ontology.outcome import ObservedOutcome, OutcomeExpectation, evaluate_outcome
from backend.services.ontology.types import (
    BusinessObjectRef,
    BusinessObjectType,
    same_business_object_class,
    same_business_object_instance,
)


def _goal(goal_id: str, objective_key: str | None) -> Goal:
    return Goal(goal_id=goal_id, objective_key=objective_key, name="Human-facing text is not identity")


def _kpi(goal_id: str, metric: str = "qualification_score") -> Kpi:
    return Kpi(kpi_id=f"kpi-{goal_id}", goal_id=goal_id, name="Score", metric=metric, unit="points")


def _signal(
    index: int,
    *,
    goal_id: str,
    goal_signature,
    intervention_key: str | None = "sales.schedule_discovery",
    lineage: EvidenceLineage | None = None,
) -> DecisionLearningSignal:
    fidelity = ExecutionFidelity.EXECUTED_AS_RECOMMENDED
    attribution = AttributionAssessment.SUPPORTED_CONTRIBUTION
    return DecisionLearningSignal(
        signal_id=f"signal-{index}",
        decision_id=f"decision-{index}",
        subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id=f"opp-{index}")],
        goal_id=goal_id,
        goal_semantic_signature=goal_signature,
        kpi_semantic_signatures=goal_signature.kpis,
        intervention_key=intervention_key,
        evidence_lineages=(lineage,) if lineage else (),
        decision_algorithm_name="weighted_criterion_evidence_v1",
        decision_algorithm_version="1",
        decision_quality=DecisionQualityAssessment(
            status=DecisionQualityStatus.WELL_SUPPORTED,
            confidence=0.9,
        ),
        execution_fidelity=fidelity,
        effectiveness=DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.EFFECTIVE,
            confidence=0.9,
            dimensions=EffectivenessDimensions(
                execution_fidelity=fidelity,
                attribution_strength=attribution,
            ),
        ),
        confidence_calibration=ConfidenceCalibrationAssessment(
            status=ConfidenceCalibrationStatus.WELL_CALIBRATED,
            original_confidence=0.8,
        ),
        consequences=ConsequenceInventory(),
        attribution_strength=attribution,
        supporting_evidence_ids=[f"evidence-{index}"],
        signal_strength=LearningSignalStrength.SUPPORTED,
        evaluated_at=datetime(2026, 1, index, tzinfo=UTC),
    )


def _source_lineage(record_id: str) -> EvidenceLineage:
    return EvidenceLineage(
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id=record_id),
        root_evidence_ids=(f"root-{record_id}",),
        resolution=EvidenceLineageResolution.KNOWN,
    )


def test_business_object_instance_and_class_are_distinct_contracts() -> None:
    left = BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="A")
    right = BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="B")
    account = BusinessObjectRef(object_type=BusinessObjectType.ACCOUNT, object_id="B")
    assert not same_business_object_instance(left, right)
    assert same_business_object_class(left, right)
    assert not same_business_object_class(left, account)


def test_goal_semantics_use_objective_then_canonical_kpis_without_none_equality() -> None:
    explicit_a = goal_semantic_signature(_goal("A", "increase_reply_rate"), [_kpi("A", "reply_rate")])
    explicit_b = goal_semantic_signature(_goal("B", "increase_reply_rate"), [_kpi("B", "reply_rate")])
    different = goal_semantic_signature(_goal("C", "increase_qualification_score"), [_kpi("C")])
    assert compare_goal_semantics(explicit_a, explicit_b).status == GoalSemanticComparisonStatus.EQUIVALENT
    assert compare_goal_semantics(explicit_a, different).status == GoalSemanticComparisonStatus.NOT_EQUIVALENT

    missing_a = goal_semantic_signature(_goal("A", None), [_kpi("A")])
    missing_b = goal_semantic_signature(_goal("B", None), [_kpi("B")])
    empty_a = goal_semantic_signature(_goal("A", None))
    empty_b = goal_semantic_signature(_goal("B", None))
    assert compare_goal_semantics(missing_a, missing_b).status == GoalSemanticComparisonStatus.PARTIALLY_EQUIVALENT
    assert compare_goal_semantics(empty_a, empty_b).status == GoalSemanticComparisonStatus.INSUFFICIENT_SEMANTICS


def test_cross_instance_recurrence_uses_owner_semantics_and_separate_roots() -> None:
    episodes = []
    for index in range(1, 4):
        goal = _goal(f"goal-{index}", "increase_qualification_score")
        signal = _signal(
            index,
            goal_id=goal.goal_id,
            goal_signature=goal_semantic_signature(goal, [_kpi(goal.goal_id)]),
            lineage=_source_lineage(f"deal-{index}"),
        )
        episodes.append(
            ExperienceEpisodeInput(
                episode_id=f"episode-{index}",
                signal=signal,
                observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
            )
        )
    result = evaluate_experience_set(episodes)
    assert result.comparisons[0].comparability == ComparabilityStatus.COMPARABLE
    assert result.comparisons[0].independence == IndependenceStatus.INDEPENDENT
    assert result.pattern_candidates[0].recurrence.strength == RecurrenceStrength.SUPPORTED


def test_derived_or_unknown_lineage_never_manufactures_independence() -> None:
    goal = _goal("goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi("goal", "reply_rate")])
    root = _source_lineage("deal-123")
    derived = EvidenceLineage(
        origin_type=EvidenceOriginType.DERIVED_FACT,
        parent_evidence_ids=("root-deal-123",),
        ancestor_evidence_ids=("root-deal-123",),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    dependent = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id="root", signal=_signal(1, goal_id="goal", goal_signature=signature, lineage=root)
            ),
            ExperienceEpisodeInput(
                episode_id="derived", signal=_signal(2, goal_id="goal", goal_signature=signature, lineage=derived)
            ),
        ]
    )
    assert dependent.comparisons[0].independence == IndependenceStatus.DEPENDENT

    unknown = evaluate_experience_set(
        [
            ExperienceEpisodeInput(episode_id="one", signal=_signal(3, goal_id="goal", goal_signature=signature)),
            ExperienceEpisodeInput(episode_id="two", signal=_signal(4, goal_id="goal", goal_signature=signature)),
        ]
    )
    assert unknown.comparisons[0].independence == IndependenceStatus.INDETERMINATE


def test_owner_and_compatibility_intervention_conflict_fails_closed() -> None:
    goal = _goal("goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi("goal", "reply_rate")])
    episode = ExperienceEpisodeInput(
        episode_id="conflict",
        signal=_signal(1, goal_id="goal", goal_signature=signature, lineage=_source_lineage("one")),
        recommendation_class="sales.send_pricing",
    )
    result = evaluate_experience_set([episode])
    assert result.unclassified_episode_ids == ("conflict",)
    assert "intervention_semantic_conflict" in result.episode_explanations["conflict"]


def test_goal_decision_outcome_feedback_semantics_survive_end_to_end() -> None:
    goal = _goal("goal-chain", "increase_qualification_score")
    baseline = _kpi(goal.goal_id)
    baseline.current_value = 60
    baseline.target_value = 80
    observed = baseline.model_copy(update={"current_value": 80, "previous_value": 60})
    outcome = evaluate_outcome(
        expectation=OutcomeExpectation(goal=goal, baseline_kpis=[baseline]),
        observed=ObservedOutcome(observed_kpis=[observed], evidence_ids=["evidence-chain"]),
        evaluated_at=datetime(2026, 2, 2, tzinfo=UTC),
    )
    semantic_signature = goal_semantic_signature(goal, [baseline])
    lineage = _source_lineage("deal-chain")
    feedback = evaluate_decision_feedback(
        snapshot=DecisionSnapshot(
            decision_id="decision-chain",
            goal_id=goal.goal_id,
            subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-chain")],
            recommendation="schedule",
            intervention_key="sales.schedule_discovery",
            goal_semantic_signature=semantic_signature,
            original_confidence=0.8,
            supporting_evidence_ids=["evidence-chain"],
            evidence_lineages=(lineage,),
            decided_at=datetime(2026, 2, 1, tzinfo=UTC),
            algorithm_name="weighted_criterion_evidence_v1",
            algorithm_version="1",
        ),
        execution=DecisionExecutionObservation(fidelity=ExecutionFidelity.NOT_EXECUTED),
        outcome=outcome,
        evaluated_at=datetime(2026, 2, 3, tzinfo=UTC),
    )
    signal = feedback.learning_signal
    assert outcome.goal_semantic_signature == semantic_signature
    assert signal.goal_semantic_signature == semantic_signature
    assert signal.kpi_semantic_signatures == semantic_signature.kpis
    assert signal.intervention_key == "sales.schedule_discovery"
    assert signal.evidence_lineages == (lineage,)
    assert signal.decision_algorithm_name == "weighted_criterion_evidence_v1"
    assert signal.decision_algorithm_version == "1"
    assert signal.algorithm == "decision_learning_signal_v1"
