import uuid
from datetime import UTC, datetime

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
from backend.services.tools.decision_actions import decision_recommend_next_action
from backend.services.tools.evidence_bridge import build_tool_action_evidence_records
from backend.services.tools.schemas import (
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
        artifact_evidence_id=f"root-{record_id}",
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


def test_source_to_derived_to_derived_forms_one_lineage_family_without_repeated_roots() -> None:
    goal = _goal("goal-family", "increase_reply_rate")
    signature = goal_semantic_signature(goal, [_kpi(goal.goal_id, "reply_rate")])
    lineages = (
        EvidenceLineage(
            artifact_evidence_id="A",
            origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
            source_identity=EvidenceSourceIdentity(source_system="crm", source_record_id="deal-123"),
            resolution=EvidenceLineageResolution.KNOWN,
        ),
        EvidenceLineage(
            artifact_evidence_id="B",
            origin_type=EvidenceOriginType.DERIVED_FACT,
            parent_evidence_ids=("A",),
            resolution=EvidenceLineageResolution.KNOWN,
        ),
        EvidenceLineage(
            artifact_evidence_id="C",
            origin_type=EvidenceOriginType.DERIVED_FACT,
            parent_evidence_ids=("B",),
            resolution=EvidenceLineageResolution.KNOWN,
        ),
    )
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
    assert "same_goal_instance_has_conflicting_owner_semantics" in comparison.reason_codes


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
