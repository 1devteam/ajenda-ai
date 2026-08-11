import uuid
from datetime import UTC, datetime

import pytest

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.worker_lease import WorkerLease
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
from backend.services.ontology.decision_snapshot_builder import build_decision_snapshot_from_recommendation
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
    EvidenceSourceIdentity,
    derived_evidence_lineage,
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
    BusinessObjectSemanticSignature,
    BusinessObjectType,
    same_business_object_class,
    same_business_object_instance,
)
from backend.services.tools.decision_actions import decision_recommend_next_action
from backend.services.tools.evidence_bridge import build_tool_action_evidence_records
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    DecisionCriterion,
    DecisionOption,
    DecisionRecommendInput,
    EvidenceFact,
    ToolInvocation,
)


def _goal(goal_id: str, objective_key: str | None) -> Goal:
    return Goal(goal_id=goal_id, objective_key=objective_key, name="Human-facing text is not identity")


def _kpi(goal_id: str, metric: str = "qualification_score") -> Kpi:
    return Kpi(kpi_id=f"kpi-{goal_id}", goal_id=goal_id, name="Score", metric=metric, unit="points")


def _signal(
    index: int,
    *,
    goal_id: str,
    goal_signature=None,
    intervention_key: str | None = "sales.schedule_discovery",
    lineage: EvidenceLineage | None = None,
    lineages: tuple[EvidenceLineage, ...] | None = None,
) -> DecisionLearningSignal:
    fidelity = ExecutionFidelity.EXECUTED_AS_RECOMMENDED
    attribution = AttributionAssessment.SUPPORTED_CONTRIBUTION
    return DecisionLearningSignal(
        signal_id=f"signal-{index}",
        decision_id=f"decision-{index}",
        subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id=f"opp-{index}")],
        goal_id=goal_id,
        goal_semantic_signature=goal_signature,
        kpi_semantic_signatures=goal_signature.kpis if goal_signature is not None else (),
        intervention_key=intervention_key,
        evidence_lineages=lineages if lineages is not None else ((lineage,) if lineage else ()),
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
        artifact_evidence_id=f"root-{record_id}",
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id=record_id),
        root_evidence_ids=(f"root-{record_id}",),
        resolution=EvidenceLineageResolution.KNOWN,
    )


def _snapshot_from_fact(
    *,
    fact_id: str,
    source_record_id: str | None = None,
    fact_lineage: EvidenceLineage | None = None,
    tenant_id: str = "tenant",
    extra_records: list[EvidenceRecord] | None = None,
    additional_fact_lineages: tuple[EvidenceLineage, ...] = (),
    result_parent_ids: tuple[str, ...] | None = None,
) -> DecisionSnapshot:
    fact_lineage = fact_lineage or EvidenceLineage(
        artifact_evidence_id=fact_id,
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id=source_record_id or fact_id),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    fact_lineages = (fact_lineage, *additional_fact_lineages)
    recommendation_input = DecisionRecommendInput(
        goal="Improve reply rate",
        options=[DecisionOption(option_id="send", label="Send", intervention_key="sales.send_followup")],
        criteria=[DecisionCriterion(criterion_id="fit", label="Fit")],
        evidence=[
            EvidenceFact(
                evidence_id=lineage.artifact_evidence_id,
                claim="Fit",
                supports_option_ids=["send"],
                supports_criterion_ids=["fit"],
                lineage=lineage,
            )
            for lineage in fact_lineages
        ],
    )
    supporting_ids = [lineage.artifact_evidence_id for lineage in fact_lineages]
    output = {
        "recommendation": "send",
        "intervention_key": "sales.send_followup",
        "supporting_evidence_ids": supporting_ids,
        "option_scores": [{"option_id": "send"}],
        "uncertainty": [],
        "algorithm": {"name": "weighted_criterion_evidence_v1", "version": "1"},
    }
    result = ActionResult(
        action="decision.recommend_next_action",
        provider="ajenda_decision",
        output=output,
        summary="Recommended send",
        confidence=0.8,
    )
    result_id = uuid.uuid4()
    result_lineage = EvidenceLineage(
        artifact_evidence_id=str(result_id),
        origin_type=EvidenceOriginType.SYSTEM_COMPUTATION,
        parent_evidence_ids=result_parent_ids or tuple(supporting_ids),
        resolution=EvidenceLineageResolution.PARTIAL,
    )
    result_record = EvidenceRecord(
        id=result_id,
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        evidence_type="execution_trace",
        evidence_source="decision_actions",
        summary="Recommended send",
        structured_payload=output,
        provenance_metadata={
            "evidence_role": "decision_recommendation_result",
            "evidence_lineage": result_lineage.model_dump(mode="json"),
        },
    )
    return build_decision_snapshot_from_recommendation(
        decision_id=f"decision-{fact_id}",
        tenant_id=tenant_id,
        recommendation_input=recommendation_input,
        recommendation_result=result,
        evidence_records=[result_record, *(extra_records or [])],
        decided_at=datetime(2026, 4, 1, tzinfo=UTC),
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


def test_same_outcome_status_never_overrides_different_objective_semantics() -> None:
    reply_goal = _goal("reply", "increase_reply_rate")
    score_goal = _goal("score", "increase_qualification_score")
    reply_outcome = evaluate_outcome(
        expectation=OutcomeExpectation(goal=reply_goal),
        observed=ObservedOutcome(),
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    score_outcome = evaluate_outcome(
        expectation=OutcomeExpectation(goal=score_goal),
        observed=ObservedOutcome(),
        evaluated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert reply_outcome.status == score_outcome.status
    assert reply_outcome.goal_semantic_signature is not None
    assert score_outcome.goal_semantic_signature is not None
    assert (
        compare_goal_semantics(reply_outcome.goal_semantic_signature, score_outcome.goal_semantic_signature).status
        == GoalSemanticComparisonStatus.NOT_EQUIVALENT
    )


def test_goal_authority_resolution_unifies_enriched_and_legacy_same_instance() -> None:
    goal = _goal("shared-goal", "increase_reply_rate")
    owned = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])
    episodes = [
        ExperienceEpisodeInput(
            episode_id="owned",
            signal=_signal(1, goal_id=goal.goal_id, goal_signature=owned, lineage=_source_lineage("owned")),
            observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
        ),
        ExperienceEpisodeInput(
            episode_id="legacy",
            signal=_signal(2, goal_id=goal.goal_id, lineage=_source_lineage("legacy")),
            observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
        ),
    ]
    result = evaluate_experience_set(episodes)
    assert result.comparisons[0].comparability == ComparabilityStatus.COMPARABLE
    assert {signature.resolved_goal_partition_identity for signature in result.signatures} == {
        "objective:increase_reply_rate"
    }
    assert len(result.partition_explanations) == 1


def test_same_goal_explicit_objective_and_contradictory_legacy_kpi_fail_closed() -> None:
    explicit_goal = _goal("shared-goal", "increase_reply_rate")
    legacy_goal = _goal("shared-goal", None)
    result = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id="explicit-kpi-a",
                signal=_signal(
                    1,
                    goal_id="shared-goal",
                    goal_signature=goal_semantic_signature(explicit_goal, [_kpi("shared-goal", "reply_rate")]),
                    lineage=_source_lineage("explicit"),
                ),
            ),
            ExperienceEpisodeInput(
                episode_id="legacy-kpi-b",
                signal=_signal(
                    2,
                    goal_id="shared-goal",
                    goal_signature=goal_semantic_signature(legacy_goal, [_kpi("shared-goal", "qualification_score")]),
                    lineage=_source_lineage("legacy"),
                ),
            ),
        ]
    )
    assert result.comparisons[0].comparability == ComparabilityStatus.INCOMPATIBLE
    assert "goal_semantic_conflict" in result.comparisons[0].reason_codes
    assert result.unclassified_episode_ids == ("explicit-kpi-a", "legacy-kpi-b")
    assert result.pattern_candidates == ()


def test_goal_authority_resolution_preserves_legacy_and_kpi_only_rules() -> None:
    legacy = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id=f"legacy-{index}",
                signal=_signal(index, goal_id="legacy-goal", lineage=_source_lineage(f"legacy-{index}")),
            )
            for index in (1, 2)
        ]
    )
    assert {signature.resolved_goal_partition_identity for signature in legacy.signatures} == {"instance:legacy-goal"}

    kpi_goal = _goal("kpi-goal", None)
    kpi_signature = goal_semantic_signature(kpi_goal, [_kpi(kpi_goal.goal_id)])
    kpi_result = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id="kpi-owned",
                signal=_signal(
                    3, goal_id=kpi_goal.goal_id, goal_signature=kpi_signature, lineage=_source_lineage("k1")
                ),
            ),
            ExperienceEpisodeInput(
                episode_id="kpi-legacy",
                signal=_signal(4, goal_id=kpi_goal.goal_id, lineage=_source_lineage("k2")),
            ),
        ]
    )
    assert len({signature.resolved_goal_partition_identity for signature in kpi_result.signatures}) == 1
    assert all(signature.goal_semantics_partial for signature in kpi_result.signatures)
    assert kpi_result.pattern_candidates[0].recurrence.strength != RecurrenceStrength.SUPPORTED


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
        artifact_evidence_id="derived-deal-123",
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


def test_partial_lineage_requires_clue_and_overlap_precedes_partial_status() -> None:
    with pytest.raises(ValueError, match="partial lineage requires"):
        EvidenceLineage(
            artifact_evidence_id="empty-partial",
            origin_type=EvidenceOriginType.DERIVED_FACT,
            resolution=EvidenceLineageResolution.PARTIAL,
        )
    source = EvidenceLineage(
        artifact_evidence_id="A",
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="deal:A"),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    overlaps = EvidenceLineage(
        artifact_evidence_id="B",
        origin_type=EvidenceOriginType.DERIVED_FACT,
        parent_evidence_ids=("A",),
        resolution=EvidenceLineageResolution.PARTIAL,
    )
    separate = EvidenceLineage(
        artifact_evidence_id="C",
        origin_type=EvidenceOriginType.DERIVED_FACT,
        parent_evidence_ids=("other",),
        resolution=EvidenceLineageResolution.PARTIAL,
    )
    goal = _goal("partial-goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])

    def independence(right: EvidenceLineage) -> IndependenceStatus:
        result = evaluate_experience_set(
            [
                ExperienceEpisodeInput(
                    episode_id="source",
                    signal=_signal(1, goal_id=goal.goal_id, goal_signature=signature, lineage=source),
                ),
                ExperienceEpisodeInput(
                    episode_id="right",
                    signal=_signal(2, goal_id=goal.goal_id, goal_signature=signature, lineage=right),
                ),
            ]
        )
        return result.comparisons[0].independence

    assert independence(overlaps) == IndependenceStatus.DEPENDENT
    assert independence(separate) == IndependenceStatus.PARTIALLY_INDEPENDENT


def test_parent_only_known_derived_lineage_is_rejected() -> None:
    with pytest.raises(ValueError, match="known derived lineage requires"):
        EvidenceLineage(
            artifact_evidence_id="derived",
            origin_type=EvidenceOriginType.DERIVED_FACT,
            parent_evidence_ids=("parent",),
            resolution=EvidenceLineageResolution.KNOWN,
        )


def test_arbitrary_partial_supporting_lineage_remains_partial_in_snapshot() -> None:
    partial = EvidenceLineage(
        artifact_evidence_id="partial-fact",
        origin_type=EvidenceOriginType.DERIVED_FACT,
        parent_evidence_ids=("unresolved-parent",),
        resolution=EvidenceLineageResolution.PARTIAL,
    )
    snapshot = _snapshot_from_fact(fact_id="partial-fact", fact_lineage=partial)
    preserved = next(
        lineage for lineage in snapshot.evidence_lineages if lineage.artifact_evidence_id == "partial-fact"
    )
    assert preserved.resolution == EvidenceLineageResolution.PARTIAL


def test_recommendation_result_stays_partial_when_parent_set_omits_supporting_fact() -> None:
    fact_a = _source_lineage("A").model_copy(update={"artifact_evidence_id": "A"})
    fact_b = _source_lineage("B").model_copy(update={"artifact_evidence_id": "B"})
    snapshot = _snapshot_from_fact(
        fact_id="A",
        fact_lineage=fact_a,
        additional_fact_lineages=(fact_b,),
        result_parent_ids=("A",),
    )
    result_lineage = next(
        lineage
        for lineage in snapshot.evidence_lineages
        if lineage.origin_type == EvidenceOriginType.SYSTEM_COMPUTATION
    )
    assert result_lineage.resolution == EvidenceLineageResolution.PARTIAL


def test_recommendation_result_becomes_known_when_complete_parent_set_is_known() -> None:
    fact_a = _source_lineage("A").model_copy(update={"artifact_evidence_id": "A"})
    fact_b = _source_lineage("B").model_copy(update={"artifact_evidence_id": "B"})
    snapshot = _snapshot_from_fact(
        fact_id="A",
        fact_lineage=fact_a,
        additional_fact_lineages=(fact_b,),
        result_parent_ids=("A", "B"),
    )
    result_lineage = next(
        lineage
        for lineage in snapshot.evidence_lineages
        if lineage.origin_type == EvidenceOriginType.SYSTEM_COMPUTATION
    )
    assert result_lineage.resolution == EvidenceLineageResolution.KNOWN


def test_source_to_derived_to_derived_forms_one_lineage_family_without_repeated_roots() -> None:
    goal = _goal("goal-family", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])
    source = EvidenceLineage(
        artifact_evidence_id="A",
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="deal-123"),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    derived_b = derived_evidence_lineage(artifact_evidence_id="B", parent=source)
    lineages = (source, derived_b, derived_evidence_lineage(artifact_evidence_id="C", parent=derived_b))
    result = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id=f"episode-{lineage.artifact_evidence_id}",
                signal=_signal(
                    index,
                    goal_id=goal.goal_id,
                    goal_signature=signature,
                    lineage=lineage,
                ),
                observation_time_provenance=ObservationTimeProvenance.SOURCE_VERIFIED,
            )
            for index, lineage in enumerate(lineages, start=1)
        ]
    )
    assert result.dependent_episode_groups == (("episode-A", "episode-B", "episode-C"),)
    assert result.pattern_candidates == ()


def test_transitive_lineage_remains_dependent_when_intermediate_artifact_is_not_evaluated() -> None:
    source = EvidenceLineage(
        artifact_evidence_id="A",
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="deal:123"),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    derived_b = derived_evidence_lineage(artifact_evidence_id="B", parent=source)
    derived_c = derived_evidence_lineage(artifact_evidence_id="C", parent=derived_b)
    goal = _goal("transitive-goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])
    result = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id="source-A",
                signal=_signal(1, goal_id=goal.goal_id, goal_signature=signature, lineage=source),
            ),
            ExperienceEpisodeInput(
                episode_id="derived-C",
                signal=_signal(2, goal_id=goal.goal_id, goal_signature=signature, lineage=derived_c),
            ),
        ]
    )
    assert derived_c.parent_evidence_ids == ("B",)
    assert "A" in derived_c.ancestor_evidence_ids
    assert result.comparisons[0].independence == IndependenceStatus.DEPENDENT
    assert result.pattern_candidates == ()


def test_snapshot_preserves_supporting_fact_roots_across_decisions() -> None:
    goal = _goal("lineage-goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])

    def comparison(source_a: str, source_b: str) -> IndependenceStatus:
        snapshot_a = _snapshot_from_fact(fact_id="fact-A", source_record_id=source_a)
        snapshot_b = _snapshot_from_fact(fact_id="fact-B", source_record_id=source_b)
        result = evaluate_experience_set(
            [
                ExperienceEpisodeInput(
                    episode_id="decision-A",
                    signal=_signal(
                        1,
                        goal_id=goal.goal_id,
                        goal_signature=signature,
                        lineages=snapshot_a.evidence_lineages,
                    ),
                ),
                ExperienceEpisodeInput(
                    episode_id="decision-B",
                    signal=_signal(
                        2,
                        goal_id=goal.goal_id,
                        goal_signature=signature,
                        lineages=snapshot_b.evidence_lineages,
                    ),
                ),
            ]
        )
        return result.comparisons[0].independence

    assert comparison("deal:123", "deal:123") == IndependenceStatus.DEPENDENT
    assert comparison("deal:123", "deal:456") == IndependenceStatus.INDEPENDENT


def test_snapshot_preserves_direct_derivation_across_decisions() -> None:
    source = EvidenceLineage(
        artifact_evidence_id="A",
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="deal:123"),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    derived = derived_evidence_lineage(artifact_evidence_id="B", parent=source)
    snapshot_a = _snapshot_from_fact(fact_id="A", fact_lineage=source)
    snapshot_b = _snapshot_from_fact(fact_id="B", fact_lineage=derived)
    goal = _goal("derived-goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])
    result = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id="uses-A",
                signal=_signal(
                    1, goal_id=goal.goal_id, goal_signature=signature, lineages=snapshot_a.evidence_lineages
                ),
            ),
            ExperienceEpisodeInput(
                episode_id="uses-B",
                signal=_signal(
                    2, goal_id=goal.goal_id, goal_signature=signature, lineages=snapshot_b.evidence_lineages
                ),
            ),
        ]
    )
    assert result.comparisons[0].independence == IndependenceStatus.DEPENDENT


def test_snapshot_excludes_unrelated_same_tenant_records_and_rejects_foreign_tenant() -> None:
    supporting_id = uuid.uuid4()
    supporting_lineage = EvidenceLineage(
        artifact_evidence_id=str(supporting_id),
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="deal:123"),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    supporting = EvidenceRecord(
        id=supporting_id,
        tenant_id="tenant",
        mission_id=uuid.uuid4(),
        evidence_type="observation",
        evidence_source="crm",
        summary="Supporting A",
        provenance_metadata={
            "source_evidence_id": "fact-A",
            "evidence_lineage": supporting_lineage.model_dump(mode="json"),
        },
    )
    unrelated_id = uuid.uuid4()
    unrelated_lineage = EvidenceLineage(
        artifact_evidence_id=str(unrelated_id),
        origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
        source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="unrelated"),
        resolution=EvidenceLineageResolution.KNOWN,
    )
    unrelated = EvidenceRecord(
        id=unrelated_id,
        tenant_id="tenant",
        mission_id=uuid.uuid4(),
        evidence_type="observation",
        evidence_source="crm",
        summary="Unrelated",
        provenance_metadata={
            "evidence_role": "decision_recommendation_result",
            "source_evidence_id": "unrelated-B",
            "evidence_lineage": unrelated_lineage.model_dump(mode="json"),
        },
    )
    snapshot = _snapshot_from_fact(fact_id="fact-A", source_record_id="deal:123", extra_records=[supporting, unrelated])
    assert supporting_lineage in snapshot.evidence_lineages
    assert unrelated_lineage not in snapshot.evidence_lineages

    foreign = unrelated.model_copy() if hasattr(unrelated, "model_copy") else unrelated
    foreign.tenant_id = "foreign-tenant"
    with pytest.raises(ValueError, match="decision tenant"):
        _snapshot_from_fact(fact_id="fact-A", source_record_id="deal:123", extra_records=[foreign])


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


def test_subject_semantic_conflict_is_rejected_and_defensively_excluded() -> None:
    goal = _goal("subject-goal", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])
    valid = _signal(1, goal_id=goal.goal_id, goal_signature=signature, lineage=_source_lineage("subject"))
    conflicting_signatures = (BusinessObjectSemanticSignature(object_type=BusinessObjectType.ACCOUNT),)
    with pytest.raises(ValueError, match="must match subject_refs"):
        DecisionLearningSignal.model_validate(
            {**valid.model_dump(mode="json"), "subject_semantic_signatures": conflicting_signatures}
        )

    malformed = valid.model_copy(update={"subject_semantic_signatures": conflicting_signatures})
    malformed_episode = ExperienceEpisodeInput.model_construct(episode_id="malformed", signal=malformed)
    result = evaluate_experience_set([malformed_episode])
    assert result.unclassified_episode_ids == ("malformed",)
    assert "subject_semantic_conflict" in result.episode_explanations["malformed"]


def test_same_goal_instance_with_conflicting_owner_objectives_is_incompatible() -> None:
    left_goal = _goal("same-goal", "increase_reply_rate")
    right_goal = _goal("same-goal", "increase_qualification_score")
    result = evaluate_experience_set(
        [
            ExperienceEpisodeInput(
                episode_id="left",
                signal=_signal(
                    1,
                    goal_id="same-goal",
                    goal_signature=goal_semantic_signature(left_goal, [_kpi("same-goal", "reply_rate")]),
                    lineage=_source_lineage("left"),
                ),
            ),
            ExperienceEpisodeInput(
                episode_id="right",
                signal=_signal(
                    2,
                    goal_id="same-goal",
                    goal_signature=goal_semantic_signature(right_goal, [_kpi("same-goal")]),
                    lineage=_source_lineage("right"),
                ),
            ),
        ]
    )
    comparison = result.comparisons[0]
    assert comparison.comparability == ComparabilityStatus.INCOMPATIBLE
    assert "goal_semantic_conflict" in comparison.reason_codes
    assert result.unclassified_episode_ids == ("left", "right")
    assert result.pattern_candidates == ()


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


def test_owner_artifacts_flow_through_recommendation_evidence_snapshot_feedback_and_experience() -> None:
    tenant_id = "tenant-semantic-chain"
    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="semantic recommendation",
        description="semantic recommendation",
        status="running",
        metadata_json={"task_type": "tool.invoke"},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    lease = WorkerLease(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=task.id,
        status="active",
        holder_identity="worker",
    )
    runtime_context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=task.id,
        mission_id=task.mission_id,
        worker_id="worker",
        lease_id=str(lease.id),
    )
    goal = Goal(
        goal_id="goal-production-chain",
        objective_key="increase_qualification_score",
        name="Increase score",
        subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-production")],
    )
    kpi = _kpi(goal.goal_id)
    recommendation_input = DecisionRecommendInput(
        goal="Increase qualification score",
        goal_ref=goal,
        subject_refs=goal.subject_refs,
        kpis=[kpi],
        options=[
            DecisionOption(
                option_id="schedule",
                label="Schedule discovery",
                intervention_key="sales.schedule_discovery",
            )
        ],
        criteria=[DecisionCriterion(criterion_id="fit", label="Fit")],
        evidence=[
            EvidenceFact(
                evidence_id="fact-fit",
                claim="Qualified fit",
                confidence=0.9,
                supports_option_ids=["schedule"],
                supports_criterion_ids=["fit"],
                lineage=EvidenceLineage(
                    artifact_evidence_id="fact-fit",
                    origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
                    source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="owner-fact"),
                    resolution=EvidenceLineageResolution.KNOWN,
                ),
            )
        ],
    )
    recommendation_result = decision_recommend_next_action(
        ToolInvocation(action="decision.recommend_next_action", input=recommendation_input.model_dump(mode="json")),
        runtime_context,
    )
    task_output = recommendation_result.model_dump(mode="json")
    task_output.update({"handler": "tool.invoke", "status": "completed"})
    runtime_lineage = LineageRecord(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=task.mission_id,
        task_id=task.id,
        worker_lease_id=lease.id,
        relationship_type="task_output",
        relationship_reason="recommendation completed",
        metadata_json={},
    )
    evidence_records = build_tool_action_evidence_records(
        task=task,
        lease=lease,
        task_output=task_output,
        lineage_record=runtime_lineage,
    )
    snapshot = build_decision_snapshot_from_recommendation(
        decision_id="decision-production-chain",
        tenant_id=tenant_id,
        recommendation_input=recommendation_input,
        recommendation_result=recommendation_result,
        evidence_records=evidence_records,
        decided_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    baseline = kpi.model_copy(update={"current_value": 60, "target_value": 80})
    observed = baseline.model_copy(update={"current_value": 80, "previous_value": 60})
    outcome = evaluate_outcome(
        expectation=OutcomeExpectation(goal=goal, baseline_kpis=[baseline]),
        observed=ObservedOutcome(observed_kpis=[observed], evidence_ids=["fact-fit"]),
        evaluated_at=datetime(2026, 3, 2, tzinfo=UTC),
    )
    feedback = evaluate_decision_feedback(
        snapshot=snapshot,
        execution=DecisionExecutionObservation(fidelity=ExecutionFidelity.NOT_EXECUTED),
        outcome=outcome,
        evaluated_at=datetime(2026, 3, 3, tzinfo=UTC),
    )
    experience = evaluate_experience_set(
        [ExperienceEpisodeInput(episode_id="production-chain", signal=feedback.learning_signal)]
    )
    signal = feedback.learning_signal
    assert snapshot.intervention_key == "sales.schedule_discovery"
    assert snapshot.goal_semantic_signature == goal_semantic_signature(goal, [kpi])
    assert snapshot.evidence_lineages[0].artifact_evidence_id == str(evidence_records[0].id)
    assert snapshot.algorithm_name == "weighted_criterion_evidence_v1"
    assert snapshot.algorithm_version == "1"
    assert signal.intervention_key == snapshot.intervention_key
    assert signal.evidence_lineages == snapshot.evidence_lineages
    assert experience.signatures[0].recommendation_class == "sales.schedule_discovery"
    assert experience.signatures[0].goal_semantic_signature == snapshot.goal_semantic_signature
