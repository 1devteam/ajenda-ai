"""Evaluation + Outcome Intelligence — analysis abilities.

``analysis.evaluate_goal_progress``: deterministic assessment of Goal/KPI/State
under explicit rules.

``analysis.evaluate_outcome``: expected vs observed outcome delta. Does not
persist OutcomeReview, recommend next actions, or execute work.
Does not modify weighted_criterion_evidence_v1.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.services.ontology.commercial_state import (
    BusinessEvent,
    BusinessStateSnapshot,
    Goal,
    Kpi,
)
from backend.services.ontology.evaluation import evaluate_goal_progress
from backend.services.ontology.outcome import (
    AttributionAssessment,
    ObservedOutcome,
    OutcomeExpectation,
    evaluate_outcome,
)
from backend.services.ontology.types import BusinessObjectRef
from backend.services.tools.action_registry import ActionDefinition, ActionRegistry
from backend.services.tools.schemas import (
    ActionResult,
    ActionRuntimeContext,
    EvidenceItem,
    SideEffectClass,
    ToolInvocation,
)


class EvaluateGoalProgressInput(BaseModel):
    """Input for analysis.evaluate_goal_progress."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    kpis: list[Kpi] = Field(default_factory=list)
    current_state: BusinessStateSnapshot | None = None
    previous_state: BusinessStateSnapshot | None = None
    events: list[BusinessEvent] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_codes: list[str] = Field(
        default_factory=list,
        description="Caller-declared evidence/information gaps (opaque codes)",
    )


class EvaluateOutcomeInput(BaseModel):
    """Input for analysis.evaluate_outcome."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    subject_refs: list[BusinessObjectRef] = Field(default_factory=list)
    baseline_kpis: list[Kpi] = Field(default_factory=list)
    baseline_snapshot: BusinessStateSnapshot | None = None
    success_criteria_codes: list[str] = Field(default_factory=list)
    observed_kpis: list[Kpi] = Field(default_factory=list)
    observed_snapshot: BusinessStateSnapshot | None = None
    events: list[BusinessEvent] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_codes: list[str] = Field(default_factory=list)
    attribution: AttributionAssessment = AttributionAssessment.NOT_ASSESSED


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    confidence: float | None,
    cluster: str,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_type="action_result_evidence",
        evidence_source="analysis_actions",
        action_name=action,
        tool_provider=provider,
        tenant_id=context.tenant_id,
        task_id=str(context.task_id),
        mission_id=str(context.mission_id) if context.mission_id is not None else None,
        summary=summary,
        structured_payload=payload,
        confidence=confidence,
        provenance={
            "runtime_path": "TaskDispatcher -> tool.invoke -> ActionRegistry",
            "cluster": cluster,
        },
        side_effect_class=SideEffectClass.NONE,
    )


def analysis_evaluate_goal_progress(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = EvaluateGoalProgressInput.model_validate(invocation.input)
    result = evaluate_goal_progress(
        goal=payload.goal,
        kpis=list(payload.kpis),
        current_state=payload.current_state,
        previous_state=payload.previous_state,
        events=list(payload.events),
        evidence_ids=list(payload.evidence_ids),
        missing_evidence_codes=list(payload.missing_evidence_codes),
    )
    output = result.model_dump(mode="json")
    summary = (
        f"Goal {result.goal_id} progress={result.status.value} "
        f"confidence={result.confidence} gaps={len(result.progress_gaps)}"
    )
    return ActionResult(
        action="analysis.evaluate_goal_progress",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.evaluate_goal_progress",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=result.confidence,
                cluster="evaluation_intelligence",
            )
        ],
        summary=summary,
        confidence=result.confidence,
    )


def analysis_evaluate_outcome(invocation: ToolInvocation, context: ActionRuntimeContext) -> ActionResult:
    payload = EvaluateOutcomeInput.model_validate(invocation.input)
    expectation = OutcomeExpectation(
        goal=payload.goal,
        subject_refs=list(payload.subject_refs),
        baseline_kpis=list(payload.baseline_kpis),
        baseline_snapshot=payload.baseline_snapshot,
        success_criteria_codes=list(payload.success_criteria_codes),
    )
    observed = ObservedOutcome(
        observed_kpis=list(payload.observed_kpis),
        observed_snapshot=payload.observed_snapshot,
        events=list(payload.events),
        evidence_ids=list(payload.evidence_ids),
        missing_evidence_codes=list(payload.missing_evidence_codes),
    )
    result = evaluate_outcome(
        expectation=expectation,
        observed=observed,
        attribution=payload.attribution,
    )
    output = result.model_dump(mode="json")
    summary = (
        f"Outcome goal={result.goal_id} status={result.status.value} "
        f"confidence={result.confidence} deltas={len(result.kpi_deltas)} "
        f"attribution={result.attribution.value}"
    )
    return ActionResult(
        action="analysis.evaluate_outcome",
        provider="ajenda_analysis",
        side_effect_class=SideEffectClass.NONE,
        output=output,
        evidence=[
            _evidence(
                context=context,
                action="analysis.evaluate_outcome",
                provider="ajenda_analysis",
                summary=summary,
                payload=output,
                confidence=result.confidence,
                cluster="outcome_intelligence",
            )
        ],
        summary=summary,
        confidence=result.confidence,
    )


def register_analysis_actions(registry: ActionRegistry) -> None:
    registry.register(
        ActionDefinition(
            name="analysis.evaluate_goal_progress",
            handler=analysis_evaluate_goal_progress,
            provider="ajenda_analysis",
            input_model=EvaluateGoalProgressInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
    registry.register(
        ActionDefinition(
            name="analysis.evaluate_outcome",
            handler=analysis_evaluate_outcome,
            provider="ajenda_analysis",
            input_model=EvaluateOutcomeInput,
            side_effect_class=SideEffectClass.NONE,
        )
    )
