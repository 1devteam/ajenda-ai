"""Decision Feedback Intelligence Slice 1 — one decision episode, one learning signal.

Architectural position:
  Evidence → Business Object → State/Event → Goal/KPI → Evaluation → Decision
  → Outcome → Decision Feedback → Experience

#412 owns Decision Feedback. Evaluates one complete decision episode and produces
a defensible feedback artifact. Does NOT convert one experience into knowledge,
policy, or behavior change.

Invariant: Observation ≠ pattern ≠ knowledge ≠ policy.

A DecisionLearningSignal is an observation from one episode — not knowledge,
policy, or a globally valid rule. #413 later compares repeated signals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.ontology.commercial_state import GoalSemanticSignature, KpiSemanticSignature
from backend.services.ontology.evidence_lineage import EvidenceLineage
from backend.services.ontology.observation_attribution import ObservationVerificationBasis
from backend.services.ontology.outcome import (
    AttributionAssessment,
    OutcomeEvaluation,
    OutcomeStatus,
)
from backend.services.ontology.types import (
    BusinessObjectRef,
    BusinessObjectSemanticSignature,
    business_object_semantic_signature,
)

DECISION_FEEDBACK_SCHEMA_VERSION = 1


class ExecutionFidelity(StrEnum):
    NOT_EXECUTED = "not_executed"
    PARTIALLY_EXECUTED = "partially_executed"
    EXECUTED_AS_RECOMMENDED = "executed_as_recommended"
    EXECUTED_WITH_MATERIAL_VARIATION = "executed_with_material_variation"
    EXECUTION_UNKNOWN = "execution_unknown"


class DecisionQualityStatus(StrEnum):
    WELL_SUPPORTED = "well_supported"
    SUPPORTED_WITH_GAPS = "supported_with_gaps"
    WEAKLY_SUPPORTED = "weakly_supported"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class DecisionEffectivenessStatus(StrEnum):
    HIGHLY_EFFECTIVE = "highly_effective"
    EFFECTIVE = "effective"
    PARTIALLY_EFFECTIVE = "partially_effective"
    INEFFECTIVE = "ineffective"
    COUNTERPRODUCTIVE = "counterproductive"
    NOT_EXECUTED = "not_executed"
    NOT_EVALUABLE = "not_evaluable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ConfidenceCalibrationStatus(StrEnum):
    WELL_CALIBRATED = "well_calibrated"
    OVERCONFIDENT = "overconfident"
    UNDERCONFIDENT = "underconfident"
    NOT_ASSESSABLE = "not_assessable"


class LearningSignalStrength(StrEnum):
    WEAK = "weak"
    CANDIDATE = "candidate"
    SUPPORTED = "supported"


class DecisionSnapshot(BaseModel):
    """Immutable decide-time context. Never evaluate with post-decision hindsight."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1, max_length=160)
    goal_id: str | None = None
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    recommendation: str = Field(min_length=1, max_length=240)
    intervention_key: str | None = Field(default=None, min_length=1, max_length=160)
    goal_semantic_signature: GoalSemanticSignature | None = None
    alternatives_considered: list[str] = Field(default_factory=list)
    option_scores: list[dict[str, Any]] = Field(default_factory=list)
    original_confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    evidence_lineages: tuple[EvidenceLineage, ...] = ()
    known_evidence_gaps: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    algorithm_name: str = Field(default="weighted_criterion_evidence_v1", max_length=120)
    algorithm_version: str = Field(default="1", max_length=40)
    decided_at: datetime
    expected_changes: list[str] = Field(default_factory=list)

    @field_validator("decision_id", "recommendation")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("required decision snapshot fields must be non-empty")
        return normalized


class DecisionExecutionObservation(BaseModel):
    """Recommendation ≠ actual execution."""

    model_config = ConfigDict(extra="forbid")

    fidelity: ExecutionFidelity
    executed_action_ref: str | None = Field(default=None, max_length=240)
    execution_evidence_ids: list[str] = Field(default_factory=list)
    execution_event_ids: list[str] = Field(default_factory=list)
    executed_at: datetime | None = None
    material_variations: list[str] = Field(default_factory=list)
    explanation_codes: list[str] = Field(default_factory=list)


class DecisionQualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DecisionQualityStatus
    confidence: float = Field(ge=0, le=1)
    required_criteria_supported_ratio: float | None = Field(default=None, ge=0, le=1)
    relied_on_inferred_evidence: bool = False
    material_gaps_acknowledged: bool = False
    alternatives_compared: bool = False
    confidence_consistent_with_evidence: bool = False
    selected_was_strongest_scored: bool | None = None
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "decision_quality_v1"


class EffectivenessDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_progress: str | None = None
    kpi_gap_closure: str | None = None
    state_movement: str | None = None
    regression_observed: bool = False
    execution_fidelity: ExecutionFidelity
    evidence_completeness: str | None = None
    attribution_strength: AttributionAssessment
    unexpected_consequence_count: int = 0


class DecisionEffectivenessEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DecisionEffectivenessStatus
    confidence: float = Field(ge=0, le=1)
    dimensions: EffectivenessDimensions
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "decision_effectiveness_v1"


class ConfidenceCalibrationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ConfidenceCalibrationStatus
    original_confidence: float = Field(ge=0, le=1)
    outcome_strength: str | None = None
    explanation_codes: list[str] = Field(default_factory=list)
    algorithm: str = "confidence_calibration_v1"


class ConsequenceInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_changes: list[str] = Field(default_factory=list)
    unexpected_positive_changes: list[str] = Field(default_factory=list)
    unexpected_negative_changes: list[str] = Field(default_factory=list)
    unresolved_changes: list[str] = Field(default_factory=list)


class DecisionLearningSignal(BaseModel):
    """Observation from one episode. NOT knowledge or policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    signal_id: str
    decision_id: str
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    goal_id: str | None = None
    subject_semantic_signatures: tuple[BusinessObjectSemanticSignature, ...] = ()
    goal_semantic_signature: GoalSemanticSignature | None = None
    kpi_semantic_signatures: tuple[KpiSemanticSignature, ...] = ()
    intervention_key: str | None = None
    evidence_lineages: tuple[EvidenceLineage, ...] = ()
    decision_algorithm_name: str | None = None
    decision_algorithm_version: str | None = None
    observation_verification_basis: ObservationVerificationBasis = ObservationVerificationBasis.UNKNOWN
    decision_quality: DecisionQualityAssessment
    execution_fidelity: ExecutionFidelity
    effectiveness: DecisionEffectivenessEvaluation
    confidence_calibration: ConfidenceCalibrationAssessment
    evidence_gaps_at_decision_time: list[str] = Field(default_factory=list)
    information_learned_after_decision: list[str] = Field(default_factory=list)
    effective_dimensions: list[str] = Field(default_factory=list)
    ineffective_dimensions: list[str] = Field(default_factory=list)
    consequences: ConsequenceInventory
    attribution_strength: AttributionAssessment
    candidate_lesson: str = Field(default="", max_length=2000)
    scope_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    signal_strength: LearningSignalStrength
    algorithm: str = "decision_learning_signal_v1"
    evaluated_at: datetime
    is_knowledge: Literal[False] = False
    is_policy: Literal[False] = False
    notes: str = (
        "A DecisionLearningSignal is an observation from one episode. "
        "It is not knowledge, policy, or a globally valid rule."
    )

    @model_validator(mode="after")
    def validate_subject_semantic_consistency(self) -> DecisionLearningSignal:
        if self.subject_refs and self.subject_semantic_signatures:
            exact_classes = {ref.object_type for ref in self.subject_refs}
            semantic_classes = {signature.object_type for signature in self.subject_semantic_signatures}
            if exact_classes != semantic_classes:
                raise ValueError("subject_semantic_signatures must match subject_refs object classes")
        return self


class DecisionFeedbackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    feedback_id: str
    decision_id: str
    goal_id: str | None = None
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    quality: DecisionQualityAssessment
    effectiveness: DecisionEffectivenessEvaluation
    calibration: ConfidenceCalibrationAssessment
    consequences: ConsequenceInventory
    learning_signal: DecisionLearningSignal
    evaluated_at: datetime
    algorithm: str = "decision_feedback_episode_v1"
    explanation_codes: list[str] = Field(default_factory=list)


def _dedupe(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in ids:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _subjects_compatible(
    decision_refs: list[BusinessObjectRef],
    outcome_refs: list[BusinessObjectRef],
) -> bool:
    if not decision_refs or not outcome_refs:
        return True
    decision_keys = {(r.object_type, r.object_id) for r in decision_refs}
    outcome_keys = {(r.object_type, r.object_id) for r in outcome_refs}
    return bool(decision_keys & outcome_keys)


def validate_decision_feedback_inputs(
    *,
    snapshot: DecisionSnapshot,
    execution: DecisionExecutionObservation,
    outcome: OutcomeEvaluation,
) -> list[str]:
    codes: list[str] = []
    if snapshot.goal_id is not None and outcome.goal_id is not None:
        if snapshot.goal_id != outcome.goal_id:
            raise ValueError(f"decision goal_id={snapshot.goal_id} must match outcome goal_id={outcome.goal_id}")
    if not _subjects_compatible(snapshot.subject_refs, outcome.subject_refs):
        raise ValueError("decision subjects are incompatible with outcome subjects; foreign context rejected")
    if execution.executed_at is not None and execution.executed_at < snapshot.decided_at:
        raise ValueError(
            "execution cannot precede decision: "
            f"executed_at={execution.executed_at.isoformat()} "
            f"decided_at={snapshot.decided_at.isoformat()}"
        )
    if execution.fidelity in {
        ExecutionFidelity.EXECUTED_AS_RECOMMENDED,
        ExecutionFidelity.PARTIALLY_EXECUTED,
        ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION,
    }:
        if execution.executed_at is None:
            codes.append("execution_time_unknown")
        if outcome.observed_at is None:
            codes.append("outcome_observation_time_unknown")
        elif execution.executed_at is not None and outcome.observed_at < execution.executed_at:
            codes.append("outcome_observation_precedes_execution")
    return codes


def assess_decision_quality(snapshot: DecisionSnapshot) -> DecisionQualityAssessment:
    """decision_quality_v1 — integrity of original decide-time process only."""

    codes: list[str] = []
    scores = list(snapshot.option_scores)
    gaps = list(snapshot.known_evidence_gaps)
    uncertainty = list(snapshot.uncertainty)

    alternatives_compared = len(snapshot.alternatives_considered) >= 1 or len(scores) >= 2
    if not alternatives_compared:
        codes.append("no_alternatives_compared")

    material_gaps_acknowledged = bool(gaps)
    if gaps:
        codes.append("material_gaps_present_at_decide_time")

    relied_on_inferred = any(
        u in {"relies_on_inferred_evidence", "inferred"} or "inferred" in u.lower() for u in uncertainty
    )
    if relied_on_inferred:
        codes.append("relied_on_inferred_evidence")

    support_ratio: float | None = None
    selected_strongest: bool | None = None
    if scores:
        chosen = next(
            (row for row in scores if row.get("option_id") == snapshot.recommendation),
            None,
        )
        if chosen is None:
            codes.append("selected_option_not_found")
            return DecisionQualityAssessment(
                status=DecisionQualityStatus.INCONCLUSIVE,
                confidence=0.2,
                required_criteria_supported_ratio=None,
                relied_on_inferred_evidence=relied_on_inferred,
                material_gaps_acknowledged=material_gaps_acknowledged,
                alternatives_compared=alternatives_compared,
                confidence_consistent_with_evidence=False,
                selected_was_strongest_scored=None,
                explanation_codes=_dedupe(codes),
            )
        dims = list(chosen.get("dimension_scores") or [])
        if dims:
            supported = [
                d for d in dims if d.get("status") in {"known", "inferred", "ok"} or float(d.get("score") or 0) > 0
            ]
            support_ratio = round(len(supported) / len(dims), 4)
        if chosen.get("missing_criterion_ids"):
            codes.append("selected_option_missing_criteria")
        if chosen.get("gaps"):
            codes.append("selected_option_had_gaps")

        feasible_scored = [
            row for row in scores if row.get("feasible", True) and float(row.get("total_score") or 0) > 0
        ]
        if feasible_scored:
            best = max(feasible_scored, key=lambda r: float(r.get("total_score") or 0))
            selected_strongest = best.get("option_id") == snapshot.recommendation
            if selected_strongest is False:
                codes.append("selected_not_strongest_scored_option")

    conf = snapshot.original_confidence
    if support_ratio is not None:
        confidence_consistent = not (conf >= 0.8 and support_ratio < 0.5) and not (
            conf <= 0.3 and support_ratio >= 0.9 and not gaps
        )
    else:
        confidence_consistent = not (conf >= 0.85 and gaps)
    if not confidence_consistent:
        codes.append("confidence_inconsistent_with_evidence")

    if support_ratio is None and not scores:
        status = DecisionQualityStatus.INCONCLUSIVE
        quality_conf = 0.4
        codes.append("no_option_scores_to_audit")
    elif support_ratio is not None and support_ratio >= 0.85 and not gaps and alternatives_compared:
        status = DecisionQualityStatus.WELL_SUPPORTED
        quality_conf = 0.85
    elif support_ratio is not None and support_ratio >= 0.6 and alternatives_compared:
        status = DecisionQualityStatus.SUPPORTED_WITH_GAPS if gaps else DecisionQualityStatus.WELL_SUPPORTED
        quality_conf = 0.7 if not gaps else 0.6
        if gaps:
            codes.append("supported_with_acknowledged_gaps")
    elif support_ratio is not None and support_ratio >= 0.35:
        status = DecisionQualityStatus.WEAKLY_SUPPORTED
        quality_conf = 0.5
        codes.append("weak_criterion_support")
    elif support_ratio is not None and support_ratio < 0.35:
        status = DecisionQualityStatus.UNSUPPORTED
        quality_conf = 0.55
        codes.append("insufficient_criterion_support")
    else:
        status = DecisionQualityStatus.INCONCLUSIVE
        quality_conf = 0.4

    if selected_strongest is False and status == DecisionQualityStatus.WELL_SUPPORTED:
        status = DecisionQualityStatus.SUPPORTED_WITH_GAPS
        codes.append("downgraded_not_strongest")

    return DecisionQualityAssessment(
        status=status,
        confidence=round(quality_conf, 4),
        required_criteria_supported_ratio=support_ratio,
        relied_on_inferred_evidence=relied_on_inferred,
        material_gaps_acknowledged=material_gaps_acknowledged,
        alternatives_compared=alternatives_compared,
        confidence_consistent_with_evidence=confidence_consistent,
        selected_was_strongest_scored=selected_strongest,
        explanation_codes=_dedupe(codes),
    )


def assess_decision_effectiveness(
    *,
    snapshot: DecisionSnapshot,
    execution: DecisionExecutionObservation,
    outcome: OutcomeEvaluation,
    quality: DecisionQualityAssessment,
) -> DecisionEffectivenessEvaluation:
    """decision_effectiveness_v1 — explicit dimension rules, fail closed."""

    codes: list[str] = []
    attribution = outcome.attribution
    fidelity = execution.fidelity

    if fidelity == ExecutionFidelity.NOT_EXECUTED:
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.NOT_EXECUTED,
            confidence=0.7,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="n/a_not_executed",
            ),
            explanation_codes=["recommendation_not_executed", "no_credit_without_execution"],
        )

    if fidelity == ExecutionFidelity.EXECUTION_UNKNOWN:
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.INSUFFICIENT_EVIDENCE,
            confidence=0.35,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="execution_unknown",
            ),
            explanation_codes=["execution_unknown_fail_closed"],
        )

    chronology_codes: list[str] = []
    if execution.executed_at is None:
        chronology_codes.append("execution_time_unknown")
    if outcome.observed_at is None:
        chronology_codes.append("outcome_observation_time_unknown")
    elif execution.executed_at is not None and outcome.observed_at < execution.executed_at:
        chronology_codes.append("outcome_observation_precedes_execution")
    if chronology_codes:
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.NOT_EVALUABLE,
            confidence=0.2,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="chronology_unknown_or_invalid",
                regression_observed=outcome.status == OutcomeStatus.REGRESSED,
            ),
            explanation_codes=[*chronology_codes, "chronology_fail_closed"],
        )

    if outcome.status == OutcomeStatus.INSUFFICIENT_EVIDENCE:
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.INSUFFICIENT_EVIDENCE,
            confidence=0.35,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="outcome_insufficient",
            ),
            explanation_codes=["outcome_insufficient_evidence"],
        )

    if fidelity == ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION:
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.NOT_EVALUABLE,
            confidence=0.4,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="materially_varied_execution",
                regression_observed=outcome.status == OutcomeStatus.REGRESSED,
            ),
            explanation_codes=[
                "material_variation_blocks_direct_recommendation_evaluation",
                "observed_episode_not_original_recommendation",
            ],
        )

    if attribution in {
        AttributionAssessment.NOT_ASSESSED,
        AttributionAssessment.INSUFFICIENT_EVIDENCE,
    }:
        codes.append("attribution_too_weak_for_strong_effectiveness")
        if outcome.status in {OutcomeStatus.ACHIEVED, OutcomeStatus.PARTIAL_PROGRESS}:
            codes.append("positive_outcome_without_attribution_not_proven_effective")
            return DecisionEffectivenessEvaluation(
                status=DecisionEffectivenessStatus.NOT_EVALUABLE,
                confidence=0.4,
                dimensions=EffectivenessDimensions(
                    goal_progress=outcome.status.value,
                    execution_fidelity=fidelity,
                    attribution_strength=attribution,
                    evidence_completeness="attribution_weak",
                ),
                explanation_codes=_dedupe(codes),
            )

    if attribution == AttributionAssessment.CONFLICTING_EVIDENCE:
        codes.append("conflicting_attribution")
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.NOT_EVALUABLE,
            confidence=0.4,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="conflicting",
                regression_observed=outcome.status == OutcomeStatus.REGRESSED,
            ),
            explanation_codes=_dedupe(codes),
        )

    regression = outcome.status == OutcomeStatus.REGRESSED
    kpi_toward = any(d.direction_assessment.value in {"toward_target", "target_reached"} for d in outcome.kpi_deltas)
    kpi_away = any(d.direction_assessment.value == "away_from_target" for d in outcome.kpi_deltas)

    if kpi_toward and not kpi_away:
        gap_closure = "closing"
    elif kpi_away and not kpi_toward:
        gap_closure = "opening"
    elif not outcome.kpi_deltas:
        gap_closure = "unknown"
    else:
        gap_closure = "mixed"

    state_movement = "observed" if outcome.state_changes and outcome.state_changes.changes else "none"
    strong_attr = attribution == AttributionAssessment.SUPPORTED_CONTRIBUTION
    temporal_only = attribution == AttributionAssessment.TEMPORAL_ASSOCIATION
    if temporal_only:
        codes.append("temporal_association_only")

    exact = fidelity == ExecutionFidelity.EXECUTED_AS_RECOMMENDED
    partial = fidelity == ExecutionFidelity.PARTIALLY_EXECUTED

    if partial and attribution != AttributionAssessment.SUPPORTED_CONTRIBUTION:
        return DecisionEffectivenessEvaluation(
            status=DecisionEffectivenessStatus.NOT_EVALUABLE,
            confidence=0.35,
            dimensions=EffectivenessDimensions(
                goal_progress=outcome.status.value,
                kpi_gap_closure=gap_closure,
                state_movement=state_movement,
                regression_observed=regression,
                execution_fidelity=fidelity,
                attribution_strength=attribution,
                evidence_completeness="partial_execution_weak_attribution",
            ),
            explanation_codes=_dedupe(
                [
                    *codes,
                    "partial_execution_with_weak_attribution_not_evaluable",
                    "observed_episode_not_original_recommendation",
                ]
            ),
        )

    if regression and strong_attr and exact:
        status = DecisionEffectivenessStatus.COUNTERPRODUCTIVE
        conf = 0.75
        codes.append("regression_with_supported_contribution")
    elif regression and (strong_attr or temporal_only):
        status = DecisionEffectivenessStatus.INEFFECTIVE
        conf = 0.65
        codes.append("regression_associated")
    elif quality.status in {
        DecisionQualityStatus.UNSUPPORTED,
        DecisionQualityStatus.WEAKLY_SUPPORTED,
    } and outcome.status in {OutcomeStatus.ACHIEVED, OutcomeStatus.PARTIAL_PROGRESS}:
        status = DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE
        conf = 0.45
        codes.append("weak_decision_lucky_outcome_not_great_decision")
    elif quality.status == DecisionQualityStatus.INCONCLUSIVE and outcome.status in {
        OutcomeStatus.ACHIEVED,
        OutcomeStatus.PARTIAL_PROGRESS,
    }:
        status = DecisionEffectivenessStatus.NOT_EVALUABLE
        conf = 0.35
        codes.append("inconclusive_decision_quality_blocks_strong_effectiveness")
    elif outcome.status == OutcomeStatus.ACHIEVED and strong_attr and exact:
        status = DecisionEffectivenessStatus.HIGHLY_EFFECTIVE
        conf = 0.85
        codes.append("achieved_exact_supported")
    elif outcome.status in {OutcomeStatus.ACHIEVED, OutcomeStatus.PARTIAL_PROGRESS} and strong_attr and exact:
        status = DecisionEffectivenessStatus.EFFECTIVE
        conf = 0.75
        codes.append("progress_exact_supported")
    elif outcome.status in {OutcomeStatus.ACHIEVED, OutcomeStatus.PARTIAL_PROGRESS} and temporal_only and exact:
        status = DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE
        conf = 0.55
        codes.append("progress_temporal_only_capped")
    elif outcome.status == OutcomeStatus.PARTIAL_PROGRESS and (exact or partial) and strong_attr:
        status = DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE
        conf = 0.65
        codes.append("partial_progress_supported")
    elif partial and outcome.status in {OutcomeStatus.ACHIEVED, OutcomeStatus.PARTIAL_PROGRESS}:
        status = DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE
        conf = 0.55
        codes.extend(
            [
                "partial_execution_caps_effectiveness",
                "observed_episode_not_original_recommendation",
            ]
        )
    elif outcome.status == OutcomeStatus.NO_MATERIAL_CHANGE:
        status = DecisionEffectivenessStatus.INEFFECTIVE
        conf = 0.6
        codes.append("no_material_change")
    else:
        status = DecisionEffectivenessStatus.NOT_EVALUABLE
        conf = 0.4
        codes.append("insufficient_dimensions_for_classification")

    return DecisionEffectivenessEvaluation(
        status=status,
        confidence=round(conf, 4),
        dimensions=EffectivenessDimensions(
            goal_progress=outcome.status.value,
            kpi_gap_closure=gap_closure,
            state_movement=state_movement,
            regression_observed=regression,
            execution_fidelity=fidelity,
            evidence_completeness="present" if outcome.supporting_evidence_ids else "thin",
            attribution_strength=attribution,
            unexpected_consequence_count=0,
        ),
        explanation_codes=_dedupe(codes),
    )


def assess_confidence_calibration(
    *,
    snapshot: DecisionSnapshot,
    execution: DecisionExecutionObservation,
    outcome: OutcomeEvaluation,
    effectiveness: DecisionEffectivenessEvaluation,
) -> ConfidenceCalibrationAssessment:
    """confidence_calibration_v1 — measurement only."""

    codes: list[str] = []
    conf = snapshot.original_confidence
    fidelity = execution.fidelity
    attribution = outcome.attribution

    if fidelity in {ExecutionFidelity.EXECUTION_UNKNOWN, ExecutionFidelity.NOT_EXECUTED}:
        return ConfidenceCalibrationAssessment(
            status=ConfidenceCalibrationStatus.NOT_ASSESSABLE,
            original_confidence=conf,
            outcome_strength=outcome.status.value,
            explanation_codes=["execution_precludes_calibration"],
        )

    if attribution in {
        AttributionAssessment.NOT_ASSESSED,
        AttributionAssessment.INSUFFICIENT_EVIDENCE,
        AttributionAssessment.CONFLICTING_EVIDENCE,
    }:
        return ConfidenceCalibrationAssessment(
            status=ConfidenceCalibrationStatus.NOT_ASSESSABLE,
            original_confidence=conf,
            outcome_strength=outcome.status.value,
            explanation_codes=["attribution_too_weak_for_calibration"],
        )

    if fidelity == ExecutionFidelity.EXECUTED_WITH_MATERIAL_VARIATION:
        return ConfidenceCalibrationAssessment(
            status=ConfidenceCalibrationStatus.NOT_ASSESSABLE,
            original_confidence=conf,
            outcome_strength=outcome.status.value,
            explanation_codes=["material_variation_precludes_calibration"],
        )

    strong_positive = effectiveness.status in {
        DecisionEffectivenessStatus.HIGHLY_EFFECTIVE,
        DecisionEffectivenessStatus.EFFECTIVE,
    }
    strong_negative = effectiveness.status in {
        DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
        DecisionEffectivenessStatus.INEFFECTIVE,
    }

    if conf >= 0.85 and strong_negative:
        status = ConfidenceCalibrationStatus.OVERCONFIDENT
        codes.append("high_confidence_poor_result")
    elif conf <= 0.45 and strong_positive:
        status = ConfidenceCalibrationStatus.UNDERCONFIDENT
        codes.append("low_confidence_strong_result")
    elif 0.45 < conf < 0.85 and (
        strong_positive or effectiveness.status == DecisionEffectivenessStatus.PARTIALLY_EFFECTIVE or strong_negative
    ):
        status = ConfidenceCalibrationStatus.WELL_CALIBRATED
        codes.append("confidence_band_aligned_with_result")
    elif conf >= 0.85 and strong_positive:
        status = ConfidenceCalibrationStatus.WELL_CALIBRATED
        codes.append("high_confidence_strong_result")
    else:
        status = ConfidenceCalibrationStatus.NOT_ASSESSABLE
        codes.append("result_strength_ambiguous_for_calibration")

    return ConfidenceCalibrationAssessment(
        status=status,
        original_confidence=conf,
        outcome_strength=outcome.status.value,
        explanation_codes=_dedupe(codes),
    )


def inventory_consequences(
    *,
    snapshot: DecisionSnapshot,
    outcome: OutcomeEvaluation,
) -> ConsequenceInventory:
    expected = list(snapshot.expected_changes)
    expected_set = {e.strip().lower() for e in expected if e.strip()}
    unexpected_pos: list[str] = []
    unexpected_neg: list[str] = []
    unresolved: list[str] = []

    for delta in outcome.kpi_deltas:
        code = f"kpi:{delta.kpi_id}:{delta.direction_assessment.value}"
        key = code.lower()
        if key in expected_set or delta.kpi_id.lower() in expected_set:
            continue
        if delta.direction_assessment.value in {"toward_target", "target_reached"}:
            unexpected_pos.append(code)
        elif delta.direction_assessment.value == "away_from_target":
            unexpected_neg.append(code)
        elif delta.direction_assessment.value == "insufficient_data":
            unresolved.append(code)

    if outcome.state_changes:
        for change in outcome.state_changes.changes:
            code = f"state:{change.key}:{change.change_type}"
            if code.lower() not in expected_set and change.key.lower() not in expected_set:
                unresolved.append(code)

    return ConsequenceInventory(
        expected_changes=expected,
        unexpected_positive_changes=_dedupe(unexpected_pos),
        unexpected_negative_changes=_dedupe(unexpected_neg),
        unresolved_changes=_dedupe(unresolved),
    )


def extract_decision_learning_signal(
    *,
    snapshot: DecisionSnapshot,
    execution: DecisionExecutionObservation,
    outcome: OutcomeEvaluation,
    quality: DecisionQualityAssessment,
    effectiveness: DecisionEffectivenessEvaluation,
    calibration: ConfidenceCalibrationAssessment,
    consequences: ConsequenceInventory,
    information_learned_after: list[str] | None = None,
    signal_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> DecisionLearningSignal:
    """decision_learning_signal_v1 — candidate lesson from one episode only."""

    attribution = outcome.attribution

    if effectiveness.status in {
        DecisionEffectivenessStatus.INSUFFICIENT_EVIDENCE,
        DecisionEffectivenessStatus.NOT_EVALUABLE,
        DecisionEffectivenessStatus.NOT_EXECUTED,
    }:
        strength = LearningSignalStrength.WEAK
    elif attribution in {
        AttributionAssessment.NOT_ASSESSED,
        AttributionAssessment.INSUFFICIENT_EVIDENCE,
        AttributionAssessment.CONFLICTING_EVIDENCE,
    }:
        strength = LearningSignalStrength.WEAK
    elif attribution == AttributionAssessment.TEMPORAL_ASSOCIATION:
        strength = LearningSignalStrength.CANDIDATE
    elif (
        effectiveness.status
        in {
            DecisionEffectivenessStatus.HIGHLY_EFFECTIVE,
            DecisionEffectivenessStatus.EFFECTIVE,
            DecisionEffectivenessStatus.COUNTERPRODUCTIVE,
        }
        and attribution == AttributionAssessment.SUPPORTED_CONTRIBUTION
    ):
        strength = LearningSignalStrength.SUPPORTED
    else:
        strength = LearningSignalStrength.CANDIDATE

    effective_dims: list[str] = []
    ineffective_dims: list[str] = []
    dims = effectiveness.dimensions
    if dims.kpi_gap_closure == "closing":
        effective_dims.append("kpi_gap_closure")
    if dims.kpi_gap_closure == "opening":
        ineffective_dims.append("kpi_gap_closure")
    if dims.regression_observed:
        ineffective_dims.append("regression")
    if dims.goal_progress in {"achieved", "partial_progress"}:
        effective_dims.append("goal_progress")
    if dims.goal_progress == "regressed":
        ineffective_dims.append("goal_progress")

    lesson_parts = [
        f"Decision {snapshot.decision_id} recommended '{snapshot.recommendation}' "
        f"with quality={quality.status.value} fidelity={execution.fidelity.value} "
        f"effectiveness={effectiveness.status.value}."
    ]
    if quality.status in {DecisionQualityStatus.UNSUPPORTED, DecisionQualityStatus.WEAKLY_SUPPORTED}:
        lesson_parts.append("Investigate whether similar weakly-supported recommendations recur under comparable gaps.")
    if effectiveness.status == DecisionEffectivenessStatus.COUNTERPRODUCTIVE:
        lesson_parts.append(
            "Investigate conditions where exact execution of this recommendation class correlates with regression."
        )
    if calibration.status == ConfidenceCalibrationStatus.OVERCONFIDENT:
        lesson_parts.append("Investigate whether confidence is systematically high relative to evidence completeness.")
    if calibration.status == ConfidenceCalibrationStatus.UNDERCONFIDENT:
        lesson_parts.append(
            "Investigate whether confidence is systematically low relative to post-hoc supported outcomes."
        )
    if consequences.unexpected_negative_changes:
        lesson_parts.append(
            f"Unexpected negative movements: {', '.join(consequences.unexpected_negative_changes[:5])}."
        )
    if len(lesson_parts) == 1:
        lesson_parts.append(
            "Preserve as single-episode observation; do not promote to policy without repeated signals."
        )

    scope = [
        f"goal_id={snapshot.goal_id}" if snapshot.goal_id else "goal_unscoped",
        f"algorithm={snapshot.algorithm_name}@{snapshot.algorithm_version}",
        f"fidelity={execution.fidelity.value}",
    ]
    invalidation = [
        "Repeated counterexamples under comparable conditions",
        "Evidence that attribution was mis-specified",
        "Material change in decision algorithm or criteria weights",
    ]
    if strength == LearningSignalStrength.WEAK:
        invalidation.append("Signal already weak; any conflicting episode invalidates candidate status")

    evidence_ids = _dedupe(
        list(snapshot.supporting_evidence_ids)
        + list(execution.execution_evidence_ids)
        + list(outcome.supporting_evidence_ids)
    )

    return DecisionLearningSignal(
        signal_id=signal_id or f"sig_{uuid4().hex[:12]}",
        decision_id=snapshot.decision_id,
        subject_refs=list(snapshot.subject_refs) or list(outcome.subject_refs),
        goal_id=snapshot.goal_id or outcome.goal_id,
        subject_semantic_signatures=tuple(
            sorted(
                outcome.subject_semantic_signatures
                or {business_object_semantic_signature(ref) for ref in (snapshot.subject_refs or outcome.subject_refs)},
                key=lambda signature: signature.object_type.value,
            )
        ),
        goal_semantic_signature=snapshot.goal_semantic_signature or outcome.goal_semantic_signature,
        kpi_semantic_signatures=outcome.kpi_semantic_signatures,
        intervention_key=snapshot.intervention_key,
        evidence_lineages=snapshot.evidence_lineages,
        decision_algorithm_name=snapshot.algorithm_name,
        decision_algorithm_version=snapshot.algorithm_version,
        observation_verification_basis=outcome.observation_timing.verification_basis,
        decision_quality=quality,
        execution_fidelity=execution.fidelity,
        effectiveness=effectiveness,
        confidence_calibration=calibration,
        evidence_gaps_at_decision_time=list(snapshot.known_evidence_gaps),
        information_learned_after_decision=list(information_learned_after or []),
        effective_dimensions=effective_dims,
        ineffective_dimensions=ineffective_dims,
        consequences=consequences,
        attribution_strength=attribution,
        candidate_lesson=" ".join(lesson_parts)[:2000],
        scope_conditions=scope,
        invalidation_conditions=invalidation,
        supporting_evidence_ids=evidence_ids,
        signal_strength=strength,
        evaluated_at=evaluated_at or datetime.now(UTC),
    )


def evaluate_decision_feedback(
    *,
    snapshot: DecisionSnapshot,
    execution: DecisionExecutionObservation,
    outcome: OutcomeEvaluation,
    information_learned_after: list[str] | None = None,
    feedback_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> DecisionFeedbackResult:
    """Compose one complete decision-episode feedback artifact.

    Post-decision information must never improve decision quality.
    """

    now = evaluated_at or datetime.now(UTC)
    validation_codes = validate_decision_feedback_inputs(snapshot=snapshot, execution=execution, outcome=outcome)

    quality = assess_decision_quality(snapshot)
    if information_learned_after:
        validation_codes.append("post_decision_information_excluded_from_quality")

    effectiveness = assess_decision_effectiveness(
        snapshot=snapshot,
        execution=execution,
        outcome=outcome,
        quality=quality,
    )
    consequences = inventory_consequences(snapshot=snapshot, outcome=outcome)
    effectiveness.dimensions.unexpected_consequence_count = len(consequences.unexpected_positive_changes) + len(
        consequences.unexpected_negative_changes
    )

    calibration = assess_confidence_calibration(
        snapshot=snapshot,
        execution=execution,
        outcome=outcome,
        effectiveness=effectiveness,
    )

    signal = extract_decision_learning_signal(
        snapshot=snapshot,
        execution=execution,
        outcome=outcome,
        quality=quality,
        effectiveness=effectiveness,
        calibration=calibration,
        consequences=consequences,
        information_learned_after=information_learned_after,
        evaluated_at=now,
    )

    return DecisionFeedbackResult(
        feedback_id=feedback_id or f"dfb_{uuid4().hex[:12]}",
        decision_id=snapshot.decision_id,
        goal_id=snapshot.goal_id or outcome.goal_id,
        subject_refs=list(snapshot.subject_refs) or list(outcome.subject_refs),
        quality=quality,
        effectiveness=effectiveness,
        calibration=calibration,
        consequences=consequences,
        learning_signal=signal,
        evaluated_at=now,
        explanation_codes=_dedupe(validation_codes + quality.explanation_codes[:3]),
    )
