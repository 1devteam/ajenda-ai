"""Outcome Intelligence Slice 1 — expected vs observed outcome assessment.

Answers: we expected X; reality became Y; did we make progress toward the
goal, by how much, and what does the evidence justify saying?

Distinct from Evaluation Intelligence:

- Evaluation asks: "Where are we now relative to the goal?"
- Outcome asks: "What changed between baseline and observed result?"

Reuses evaluate_kpi / compare_state_snapshots / evaluate_goal_progress.
Does not persist OutcomeReview, execute work, claim causation, or call an LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from backend.services.ontology.commercial_state import (
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    Kpi,
    KpiDirection,
)
from backend.services.ontology.evaluation import (
    EvaluationResult,
    GapKind,
    GoalProgressStatus,
    ProgressGap,
    StateComparison,
    compare_state_snapshots,
    evaluate_goal_progress,
    evaluate_kpi,
)
from backend.services.ontology.types import BusinessObjectRef
from pydantic import BaseModel, ConfigDict, Field

OUTCOME_SCHEMA_VERSION = 1


class OutcomeStatus(StrEnum):
    """Conservative outcome assessment — no success claim without contract support."""

    ACHIEVED = "achieved"
    PARTIAL_PROGRESS = "partial_progress"
    NO_MATERIAL_CHANGE = "no_material_change"
    REGRESSED = "regressed"
    INCONCLUSIVE = "inconclusive"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class AttributionAssessment(StrEnum):
    """Explicit non-causal attribution of observed change to a prior decision/action."""

    NOT_ASSESSED = "not_assessed"
    TEMPORAL_ASSOCIATION = "temporal_association"
    SUPPORTED_CONTRIBUTION = "supported_contribution"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class DirectionAssessment(StrEnum):
    """Movement of a KPI relative to its target between baseline and observed."""

    TOWARD_TARGET = "toward_target"
    AWAY_FROM_TARGET = "away_from_target"
    UNCHANGED = "unchanged"
    TARGET_REACHED = "target_reached"
    INSUFFICIENT_DATA = "insufficient_data"


class KpiOutcomeDelta(BaseModel):
    """Per-KPI before → after → target delta (inspectable, deterministic)."""

    model_config = ConfigDict(extra="forbid")

    kpi_id: str
    metric: str
    direction: KpiDirection
    before: float | None = None
    after: float | None = None
    target: float | None = None
    absolute_change: float | None = None
    previous_gap: float | None = None
    remaining_gap: float | None = None
    gap_closed: float | None = None
    gap_closure_ratio: float | None = Field(
        default=None,
        description="Fraction of previous gap closed (0-1+); None if not computable",
    )
    target_reached: bool | None = None
    direction_assessment: DirectionAssessment = DirectionAssessment.INSUFFICIENT_DATA
    explanation_codes: list[str] = Field(default_factory=list)


class OutcomeExpectation(BaseModel):
    """Baseline condition against which observed results are judged."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    baseline_kpis: list[Kpi] = Field(default_factory=list)
    baseline_snapshot: BusinessStateSnapshot | None = None
    success_criteria_codes: list[str] = Field(
        default_factory=list,
        description="Opaque structured success criteria codes (not free prose)",
    )


class ObservedOutcome(BaseModel):
    """Observed condition after the interval under assessment."""

    model_config = ConfigDict(extra="forbid")

    observed_kpis: list[Kpi] = Field(default_factory=list)
    observed_snapshot: BusinessStateSnapshot | None = None
    events: list[BusinessEvent] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_codes: list[str] = Field(default_factory=list)


class CriteriaResult(BaseModel):
    """Structured result for one success-criteria code."""

    model_config = ConfigDict(extra="forbid")

    code: str
    satisfied: bool | None = None
    explanation_code: str = ""


class OutcomeEvaluation(BaseModel):
    """Typed assessment of expected vs observed outcome. Not an OutcomeReview."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_evaluation_id: str
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    goal_id: str | None = None
    status: OutcomeStatus
    kpi_deltas: list[KpiOutcomeDelta] = Field(default_factory=list)
    state_changes: StateComparison | None = None
    criteria_results: list[CriteriaResult] = Field(default_factory=list)
    baseline_evaluation: EvaluationResult | None = None
    observed_evaluation: EvaluationResult | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    evidence_gaps: list[ProgressGap] = Field(default_factory=list)
    attribution: AttributionAssessment = AttributionAssessment.NOT_ASSESSED
    confidence: float = Field(ge=0, le=1)
    explanation_codes: list[str] = Field(default_factory=list)
    evaluated_at: datetime
    algorithm: str = "outcome_delta_v1"


def _signed_gap(*, value: float | None, target: float | None, direction: KpiDirection) -> float | None:
    if value is None or target is None:
        return None
    if direction == KpiDirection.INCREASE:
        return target - value
    if direction == KpiDirection.DECREASE:
        return value - target
    return abs(value - target)


def _kpi_outcome_delta(*, baseline: Kpi, observed: Kpi) -> KpiOutcomeDelta:
    """Compute before/after/target delta for one KPI pair (same kpi_id)."""

    before = baseline.current_value
    after = observed.current_value
    target = observed.target_value if observed.target_value is not None else baseline.target_value
    direction = observed.direction
    codes: list[str] = []

    if before is None or after is None or target is None:
        return KpiOutcomeDelta(
            kpi_id=observed.kpi_id,
            metric=observed.metric,
            direction=direction,
            before=before,
            after=after,
            target=target,
            direction_assessment=DirectionAssessment.INSUFFICIENT_DATA,
            explanation_codes=["kpi_insufficient_data"],
        )

    absolute_change = after - before
    previous_gap = _signed_gap(value=before, target=target, direction=direction)
    remaining_gap = _signed_gap(value=after, target=target, direction=direction)
    assert previous_gap is not None and remaining_gap is not None

    gap_closed = previous_gap - remaining_gap
    if previous_gap == 0:
        gap_closure_ratio = 1.0 if remaining_gap == 0 else 0.0
    else:
        gap_closure_ratio = gap_closed / previous_gap

    observed_for_eval = observed.model_copy(
        update={
            "current_value": after,
            "target_value": target,
            "previous_value": before,
        }
    )
    after_eval = evaluate_kpi(observed_for_eval)
    target_reached = bool(after_eval.target_reached)

    if target_reached:
        direction_assessment = DirectionAssessment.TARGET_REACHED
        codes.append("target_reached")
    elif direction == KpiDirection.INCREASE:
        if absolute_change > 0:
            direction_assessment = DirectionAssessment.TOWARD_TARGET
            codes.append("gap_reduced")
        elif absolute_change < 0:
            direction_assessment = DirectionAssessment.AWAY_FROM_TARGET
            codes.append("gap_increased")
        else:
            direction_assessment = DirectionAssessment.UNCHANGED
            codes.append("no_material_change")
    elif direction == KpiDirection.DECREASE:
        if absolute_change < 0:
            direction_assessment = DirectionAssessment.TOWARD_TARGET
            codes.append("gap_reduced")
        elif absolute_change > 0:
            direction_assessment = DirectionAssessment.AWAY_FROM_TARGET
            codes.append("gap_increased")
        else:
            direction_assessment = DirectionAssessment.UNCHANGED
            codes.append("no_material_change")
    else:  # MAINTAIN
        if remaining_gap < previous_gap:
            direction_assessment = DirectionAssessment.TOWARD_TARGET
            codes.append("gap_reduced")
        elif remaining_gap > previous_gap:
            direction_assessment = DirectionAssessment.AWAY_FROM_TARGET
            codes.append("gap_increased")
        else:
            direction_assessment = DirectionAssessment.UNCHANGED
            codes.append("no_material_change")

    return KpiOutcomeDelta(
        kpi_id=observed.kpi_id,
        metric=observed.metric,
        direction=direction,
        before=before,
        after=after,
        target=target,
        absolute_change=round(absolute_change, 6),
        previous_gap=round(previous_gap, 6),
        remaining_gap=round(remaining_gap, 6),
        gap_closed=round(gap_closed, 6),
        gap_closure_ratio=round(gap_closure_ratio, 6),
        target_reached=target_reached,
        direction_assessment=direction_assessment,
        explanation_codes=codes,
    )


def _pair_kpis(baseline_kpis: list[Kpi], observed_kpis: list[Kpi]) -> list[tuple[Kpi, Kpi]]:
    observed_by_id = {k.kpi_id: k for k in observed_kpis}
    pairs: list[tuple[Kpi, Kpi]] = []
    for base in baseline_kpis:
        if base.kpi_id in observed_by_id:
            pairs.append((base, observed_by_id[base.kpi_id]))
    return pairs


def _aggregate_status(
    *,
    deltas: list[KpiOutcomeDelta],
    evidence_gaps: list[ProgressGap],
    has_required_pairs: bool,
) -> tuple[OutcomeStatus, float, list[str]]:
    codes: list[str] = []

    if evidence_gaps and not deltas:
        return OutcomeStatus.INSUFFICIENT_EVIDENCE, 0.35, ["required_evidence_missing"]

    if not has_required_pairs and not deltas:
        return OutcomeStatus.INSUFFICIENT_EVIDENCE, 0.3, ["no_kpi_pairs"]

    if any(d.direction_assessment == DirectionAssessment.INSUFFICIENT_DATA for d in deltas):
        if all(d.direction_assessment == DirectionAssessment.INSUFFICIENT_DATA for d in deltas):
            return OutcomeStatus.INSUFFICIENT_EVIDENCE, 0.35, ["kpi_insufficient_data"]

    measurable = [d for d in deltas if d.direction_assessment != DirectionAssessment.INSUFFICIENT_DATA]
    if not measurable:
        return OutcomeStatus.INSUFFICIENT_EVIDENCE, 0.35, ["kpi_insufficient_data"]

    reached = [d for d in measurable if d.direction_assessment == DirectionAssessment.TARGET_REACHED]
    toward = [d for d in measurable if d.direction_assessment == DirectionAssessment.TOWARD_TARGET]
    away = [d for d in measurable if d.direction_assessment == DirectionAssessment.AWAY_FROM_TARGET]
    unchanged = [d for d in measurable if d.direction_assessment == DirectionAssessment.UNCHANGED]

    if len(reached) == len(measurable):
        codes.append("all_targets_reached")
        confidence = 0.9 if not evidence_gaps else 0.7
        if evidence_gaps:
            codes.append("required_evidence_missing")
        return OutcomeStatus.ACHIEVED, confidence, codes

    if away and not toward and not reached:
        codes.append("regressed")
        return OutcomeStatus.REGRESSED, 0.75, codes

    if toward or reached:
        codes.append("partial_progress")
        if away:
            codes.append("mixed_direction")
        confidence = 0.7 if not evidence_gaps else 0.55
        if evidence_gaps:
            codes.append("required_evidence_missing")
        return OutcomeStatus.PARTIAL_PROGRESS, confidence, codes

    if unchanged and not toward and not away and not reached:
        codes.append("no_material_change")
        return OutcomeStatus.NO_MATERIAL_CHANGE, 0.65, codes

    codes.append("inconclusive")
    return OutcomeStatus.INCONCLUSIVE, 0.45, codes


def evaluate_outcome(
    *,
    expectation: OutcomeExpectation,
    observed: ObservedOutcome,
    attribution: AttributionAssessment = AttributionAssessment.NOT_ASSESSED,
    outcome_evaluation_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> OutcomeEvaluation:
    """Deterministic expected-vs-observed outcome assessment.

    Reuses Evaluation Intelligence primitives. Does not write OutcomeReview.
    Attribution is caller-supplied; this function never upgrades it to causation.
    """

    goal = expectation.goal
    pairs = _pair_kpis(expectation.baseline_kpis, observed.observed_kpis)
    deltas = [_kpi_outcome_delta(baseline=b, observed=o) for b, o in pairs]

    baseline_ids = {k.kpi_id for k in expectation.baseline_kpis}
    for obs in observed.observed_kpis:
        if obs.kpi_id not in baseline_ids:
            deltas.append(
                KpiOutcomeDelta(
                    kpi_id=obs.kpi_id,
                    metric=obs.metric,
                    direction=obs.direction,
                    before=None,
                    after=obs.current_value,
                    target=obs.target_value,
                    direction_assessment=DirectionAssessment.INSUFFICIENT_DATA,
                    explanation_codes=["baseline_kpi_missing"],
                )
            )

    state_cmp: StateComparison | None = None
    if expectation.baseline_snapshot is not None and observed.observed_snapshot is not None:
        state_cmp = compare_state_snapshots(expectation.baseline_snapshot, observed.observed_snapshot)

    evidence_gaps = [
        ProgressGap(kind=GapKind.EVIDENCE, code=code, message=f"Missing evidence: {code}")
        for code in observed.missing_evidence_codes
    ]

    baseline_eval = evaluate_goal_progress(
        goal=goal,
        kpis=list(expectation.baseline_kpis),
        current_state=expectation.baseline_snapshot,
        previous_state=None,
        events=[],
        evidence_ids=[],
        missing_evidence_codes=[],
    )
    observed_eval = evaluate_goal_progress(
        goal=goal,
        kpis=list(observed.observed_kpis),
        current_state=observed.observed_snapshot,
        previous_state=expectation.baseline_snapshot,
        events=list(observed.events),
        evidence_ids=list(observed.evidence_ids),
        missing_evidence_codes=list(observed.missing_evidence_codes),
    )

    required_pair_count = sum(1 for b, o in pairs if b.required or o.required)
    status, confidence, explanation_codes = _aggregate_status(
        deltas=deltas,
        evidence_gaps=evidence_gaps,
        has_required_pairs=required_pair_count > 0 or bool(pairs),
    )

    if state_cmp is not None and state_cmp.changes:
        explanation_codes.append("desired_state_transition_observed")

    if observed_eval.status == GoalProgressStatus.ACHIEVED and status != OutcomeStatus.ACHIEVED:
        if any(d.target_reached for d in deltas):
            status = OutcomeStatus.ACHIEVED
            explanation_codes.append("observed_goal_achieved")
            confidence = max(confidence, 0.85)

    criteria_results: list[CriteriaResult] = []
    gap_codes = {g.code for g in evidence_gaps}
    for code in expectation.success_criteria_codes:
        if status == OutcomeStatus.ACHIEVED and code not in gap_codes:
            criteria_results.append(CriteriaResult(code=code, satisfied=True, explanation_code="criteria_met"))
        elif status in {OutcomeStatus.INSUFFICIENT_EVIDENCE, OutcomeStatus.INCONCLUSIVE}:
            criteria_results.append(CriteriaResult(code=code, satisfied=None, explanation_code="criteria_unassessable"))
        else:
            criteria_results.append(CriteriaResult(code=code, satisfied=False, explanation_code="criteria_not_met"))

    subject_refs = list(expectation.subject_refs) or list(goal.subject_refs)
    if observed.observed_snapshot is not None:
        ref = observed.observed_snapshot.subject_ref
        if not any(r.object_type == ref.object_type and r.object_id == ref.object_id for r in subject_refs):
            subject_refs.append(ref)

    supporting = list(dict.fromkeys(observed.evidence_ids))
    if observed.observed_snapshot is not None:
        supporting.extend(eid for eid in observed.observed_snapshot.evidence_ids if eid not in supporting)

    if attribution == AttributionAssessment.SUPPORTED_CONTRIBUTION:
        explanation_codes.append("attribution_supported_contribution_caller_asserted")
    elif attribution == AttributionAssessment.TEMPORAL_ASSOCIATION:
        explanation_codes.append("attribution_temporal_association")

    return OutcomeEvaluation(
        outcome_evaluation_id=outcome_evaluation_id or f"out_{uuid4().hex[:12]}",
        subject_refs=subject_refs,
        goal_id=goal.goal_id,
        status=status,
        kpi_deltas=deltas,
        state_changes=state_cmp,
        criteria_results=criteria_results,
        baseline_evaluation=baseline_eval,
        observed_evaluation=observed_eval,
        supporting_evidence_ids=supporting,
        evidence_gaps=evidence_gaps,
        attribution=attribution,
        confidence=round(confidence, 4),
        explanation_codes=list(dict.fromkeys(explanation_codes)),
        evaluated_at=evaluated_at or datetime.now(UTC),
    )
