"""Evaluation Intelligence Slice 1 — deterministic assessment primitives.

Interprets Goal / KPI / State / Events / Evidence under explicit rules.
Does not recommend actions, execute work, or call an LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.services.ontology.commercial_state import (
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    Kpi,
    KpiDirection,
)
from backend.services.ontology.types import BusinessObjectRef

EVALUATION_SCHEMA_VERSION = 1


class GoalProgressStatus(StrEnum):
    """Outcome of goal progress evaluation (distinct from Goal lifecycle status)."""

    ACHIEVED = "achieved"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"
    INSUFFICIENT_DATA = "insufficient_data"


class GapKind(StrEnum):
    PERFORMANCE = "performance"
    EVIDENCE = "evidence"
    INFORMATION = "information"


class KpiEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kpi_id: str
    metric: str
    direction: KpiDirection
    current_value: float | None = None
    target_value: float | None = None
    previous_value: float | None = None
    gap: float | None = None
    change: float | None = None
    attainment: float | None = Field(default=None, description="0-1 ratio when computable")
    target_reached: bool | None = None
    improving: bool | None = None
    status: Literal["ok", "gap", "exceeded", "insufficient_data", "within_tolerance"] = "insufficient_data"
    explanation: str = ""


class StateAttributeChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    change_type: Literal["added", "removed", "changed"]
    before: Any | None = None
    after: Any | None = None


class StateComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    earlier_snapshot_id: str
    later_snapshot_id: str
    changes: list[StateAttributeChange] = Field(default_factory=list)
    explanation: str = ""


class ProgressGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: GapKind
    code: str
    message: str
    kpi_id: str | None = None
    evidence_id: str | None = None


class EvaluationResult(BaseModel):
    """Interpretation of commercial + evidence inputs under explicit rules."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    evaluation_id: str
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    goal_id: str | None = None
    status: GoalProgressStatus
    confidence: float = Field(ge=0, le=1)
    kpi_evaluations: list[KpiEvaluation] = Field(default_factory=list)
    state_changes: StateComparison | None = None
    progress_gaps: list[ProgressGap] = Field(default_factory=list)
    evidence_gaps: list[ProgressGap] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    evaluated_at: datetime
    algorithm: str = "goal_progress_evaluation_v1"
    explanations: list[str] = Field(default_factory=list)
    recent_event_ids: list[str] = Field(default_factory=list)


def evaluate_kpi(kpi: Kpi) -> KpiEvaluation:
    """Deterministic KPI current vs target (and optional previous for change)."""

    current = kpi.current_value
    target = kpi.target_value
    previous = kpi.previous_value
    change = (current - previous) if current is not None and previous is not None else None

    if current is None or target is None:
        return KpiEvaluation(
            kpi_id=kpi.kpi_id,
            metric=kpi.metric,
            direction=kpi.direction,
            current_value=current,
            target_value=target,
            previous_value=previous,
            change=change,
            status="insufficient_data",
            explanation="current_value or target_value missing",
        )

    if kpi.direction == KpiDirection.INCREASE:
        gap = target - current
        target_reached = current >= target
        attainment = None if target == 0 else max(0.0, min(1.0, current / target))
        improving = change is not None and change > 0
        if target_reached:
            status: Literal["ok", "gap", "exceeded", "insufficient_data", "within_tolerance"] = (
                "exceeded" if current > target else "ok"
            )
            explanation = f"current {current} meets/exceeds target {target} (increase)"
        else:
            status = "gap"
            explanation = f"need +{gap} to reach target {target} from {current}"
    elif kpi.direction == KpiDirection.DECREASE:
        gap = current - target
        target_reached = current <= target
        if current == 0 and target == 0:
            attainment = 1.0
        elif current == 0:
            attainment = 0.0
        else:
            attainment = max(0.0, min(1.0, target / current))
        improving = change is not None and change < 0
        if target_reached:
            status = "exceeded" if current < target else "ok"
            explanation = f"current {current} meets/under target {target} (decrease)"
        else:
            status = "gap"
            explanation = f"need -{gap} to reach target {target} from {current}"
    else:  # MAINTAIN
        tol = kpi.maintain_tolerance if kpi.maintain_tolerance is not None else 0.0
        gap = abs(current - target)
        target_reached = gap <= tol
        attainment = 1.0 if target_reached else max(0.0, 1.0 - (gap / (abs(target) + 1e-9)))
        # previous_value=0 is a legitimate measurement; never use truthiness
        improving = (
            change is not None
            and previous is not None
            and abs(current - target) < abs(previous - target)
        )
        if target_reached:
            status = "within_tolerance" if gap > 0 else "ok"
            explanation = f"current {current} within ±{tol} of target {target}"
        else:
            status = "gap"
            explanation = f"|current-target|={gap} exceeds tolerance {tol}"

    return KpiEvaluation(
        kpi_id=kpi.kpi_id,
        metric=kpi.metric,
        direction=kpi.direction,
        current_value=current,
        target_value=target,
        previous_value=previous,
        gap=round(gap, 6),
        change=round(change, 6) if change is not None else None,
        attainment=round(attainment, 6) if attainment is not None else None,
        target_reached=target_reached,
        improving=improving,
        status=status,
        explanation=explanation,
    )


def compare_state_snapshots(
    earlier: BusinessStateSnapshot,
    later: BusinessStateSnapshot,
) -> StateComparison:
    """Explicit attribute deltas between two snapshots of the same subject.

    Rejects different subjects and reversed chronology. Unknown is not
    regression; different subjects are not comparable state.
    """

    if earlier.subject_ref.object_type != later.subject_ref.object_type or (
        earlier.subject_ref.object_id != later.subject_ref.object_id
    ):
        raise ValueError(
            "state comparison requires identical subject_ref on both snapshots; "
            f"got {earlier.subject_ref.object_type}:{earlier.subject_ref.object_id} vs "
            f"{later.subject_ref.object_type}:{later.subject_ref.object_id}"
        )

    if later.captured_at < earlier.captured_at:
        raise ValueError(
            "state comparison requires chronological order: later.captured_at must be "
            f">= earlier.captured_at; got later={later.captured_at.isoformat()} "
            f"earlier={earlier.captured_at.isoformat()}"
        )

    before = dict(earlier.attributes)
    after = dict(later.attributes)
    changes: list[StateAttributeChange] = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            changes.append(StateAttributeChange(key=key, change_type="added", after=after[key]))
        elif key not in after:
            changes.append(StateAttributeChange(key=key, change_type="removed", before=before[key]))
        elif before[key] != after[key]:
            changes.append(
                StateAttributeChange(
                    key=key, change_type="changed", before=before[key], after=after[key]
                )
            )
    explanation = (
        f"{len(changes)} attribute change(s) from {earlier.snapshot_id} → {later.snapshot_id}"
        if changes
        else "No attribute differences"
    )
    return StateComparison(
        earlier_snapshot_id=earlier.snapshot_id,
        later_snapshot_id=later.snapshot_id,
        changes=changes,
        explanation=explanation,
    )


def evaluate_goal_progress(
    *,
    goal: Goal,
    kpis: list[Kpi],
    current_state: BusinessStateSnapshot | None = None,
    previous_state: BusinessStateSnapshot | None = None,
    events: list[BusinessEvent] | None = None,
    evidence_ids: list[str] | None = None,
    missing_evidence_codes: list[str] | None = None,
    evaluation_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> EvaluationResult:
    """Aggregate KPI evaluations into goal progress status with inspectable gaps.

    Conservative V1 rules (hardened):
    - Only KPIs whose goal_id matches the requested Goal are evaluated.
    - Foreign-goal KPIs never influence status.
    - No matching goal-scoped KPIs → INSUFFICIENT_DATA (explicit mismatch explanation).
    - OFF_TRACK only when measured movement is against the target direction.
    - Unknown / missing previous is not regression; below-target with no prior
      measurement uses AT_RISK (or INSUFFICIENT_DATA when values themselves are missing).
    - achieved: all required KPIs target_reached
    - on_track / at_risk follow measured improvement + remaining gaps
    """

    events = events or []
    evidence_ids = list(evidence_ids or [])
    missing_evidence_codes = list(missing_evidence_codes or [])

    # Strict goal scoping — no fallback to foreign KPIs
    scoped = [k for k in kpis if k.goal_id == goal.goal_id]
    kpi_evals = [evaluate_kpi(k) for k in scoped]
    eval_by_id = {e.kpi_id: e for e in kpi_evals}
    required_pairs = [(k, eval_by_id[k.kpi_id]) for k in scoped if k.required and k.kpi_id in eval_by_id]

    progress_gaps: list[ProgressGap] = []
    evidence_gaps: list[ProgressGap] = []
    explanations: list[str] = []

    for code in missing_evidence_codes:
        evidence_gaps.append(ProgressGap(kind=GapKind.EVIDENCE, code=code, message=f"Missing evidence: {code}"))

    for _k, ev in required_pairs:
        if ev.status == "insufficient_data":
            progress_gaps.append(
                ProgressGap(
                    kind=GapKind.INFORMATION,
                    code=f"kpi_insufficient:{ev.kpi_id}",
                    message=ev.explanation,
                    kpi_id=ev.kpi_id,
                )
            )
        elif ev.target_reached is False:
            progress_gaps.append(
                ProgressGap(
                    kind=GapKind.PERFORMANCE,
                    code=f"kpi_gap:{ev.kpi_id}",
                    message=ev.explanation,
                    kpi_id=ev.kpi_id,
                )
            )

    state_cmp: StateComparison | None = None
    if previous_state is not None and current_state is not None:
        state_cmp = compare_state_snapshots(previous_state, current_state)
        explanations.append(state_cmp.explanation)

    if not scoped:
        status = GoalProgressStatus.INSUFFICIENT_DATA
        confidence = 0.3
        explanations.append(
            f"No KPIs scoped to goal_id={goal.goal_id}; foreign or empty KPI list cannot drive status"
        )
    elif not required_pairs:
        status = GoalProgressStatus.INSUFFICIENT_DATA
        confidence = 0.3
        explanations.append(
            f"No required KPIs matched goal_id={goal.goal_id}; cannot evaluate progress"
        )
    elif any(e.status == "insufficient_data" for _, e in required_pairs):
        status = GoalProgressStatus.INSUFFICIENT_DATA
        confidence = 0.4
        explanations.append("One or more required KPIs lack current or target values")
    elif all(e.target_reached for _, e in required_pairs):
        status = GoalProgressStatus.ACHIEVED
        confidence = 0.9
        explanations.append("All required KPIs meet targets")
    else:
        moving_against = False
        any_improving = False
        any_measured_change = False
        for k, e in required_pairs:
            if e.target_reached:
                continue
            if e.change is not None:
                any_measured_change = True
                if k.direction == KpiDirection.INCREASE and e.change < 0:
                    moving_against = True
                elif k.direction == KpiDirection.DECREASE and e.change > 0:
                    moving_against = True
                elif k.direction == KpiDirection.MAINTAIN and e.improving is False and e.change != 0:
                    # Measured movement away from target under maintain
                    moving_against = True
                elif e.improving:
                    any_improving = True
            elif e.improving:
                any_improving = True

        if moving_against:
            status = GoalProgressStatus.OFF_TRACK
            confidence = 0.75
            explanations.append("Required KPI moved against its target direction")
        elif any_improving and progress_gaps:
            status = GoalProgressStatus.AT_RISK
            confidence = 0.65
            explanations.append("Progress exists but required gaps remain")
        elif any_improving and not evidence_gaps:
            status = GoalProgressStatus.ON_TRACK
            confidence = 0.7
            explanations.append("Required metrics improving without evidence blockers")
        elif progress_gaps and not any_measured_change:
            # Below target but no previous measurement → unknown is not regression
            status = GoalProgressStatus.AT_RISK
            confidence = 0.55
            explanations.append(
                "Required gaps present; no prior measurement so improvement cannot be assessed "
                "(unknown is not regression)"
            )
        elif progress_gaps and not any_improving:
            status = GoalProgressStatus.OFF_TRACK
            confidence = 0.6
            explanations.append("Required gaps with measured movement that is not improving")
        else:
            status = GoalProgressStatus.AT_RISK
            confidence = 0.55
            explanations.append("Gaps remain; improvement not fully established")

    if evidence_gaps and status in {GoalProgressStatus.ON_TRACK, GoalProgressStatus.ACHIEVED}:
        status = GoalProgressStatus.AT_RISK
        explanations.append("Evidence gaps prevent full confidence in status")
        confidence = min(confidence, 0.55)

    subject_refs = list(goal.subject_refs)
    if current_state is not None:
        ref = current_state.subject_ref
        if not any(r.object_type == ref.object_type and r.object_id == ref.object_id for r in subject_refs):
            subject_refs.append(ref)

    supporting = list(dict.fromkeys(evidence_ids))
    if current_state is not None:
        supporting.extend(eid for eid in current_state.evidence_ids if eid not in supporting)

    return EvaluationResult(
        evaluation_id=evaluation_id or f"eval_{uuid4().hex[:12]}",
        subject_refs=subject_refs,
        goal_id=goal.goal_id,
        status=status,
        confidence=round(confidence, 4),
        kpi_evaluations=kpi_evals,
        state_changes=state_cmp,
        progress_gaps=progress_gaps,
        evidence_gaps=evidence_gaps,
        supporting_evidence_ids=supporting,
        evaluated_at=evaluated_at or datetime.now(UTC),
        explanations=explanations,
        recent_event_ids=[e.event_id for e in events],
    )
