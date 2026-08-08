"""Evaluation Intelligence — analysis abilities (Slice 1).

``analysis.evaluate_goal_progress``: deterministic assessment of Goal/KPI/State
under explicit rules. Does not recommend next actions or execute work.
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


def _evidence(
    *,
    context: ActionRuntimeContext,
    action: str,
    provider: str,
    summary: str,
    payload: dict[str, Any],
    confidence: float | None,
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
            "cluster": "evaluation_intelligence",
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
