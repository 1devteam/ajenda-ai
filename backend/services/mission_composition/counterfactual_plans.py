"""Deterministic, non-executable counterfactual plan comparisons."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.contracts import MissionCompositionRecord

RiskLevel = Literal["low", "medium", "high"]


class CounterfactualPlan(BaseModel):
    """A bounded plan estimate; it is never admitted to runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1, max_length=80)
    strategy: Literal["selected", "read_only_projection"]
    action_names: tuple[str, ...] = ()
    expected_artifact_keys: tuple[str, ...] = ()
    evidence_score: float = Field(ge=0.0, le=1.0)
    estimated_cost_units: int = Field(ge=0)
    estimated_latency_units: int = Field(ge=0)
    risk_level: RiskLevel
    completeness: Literal["full", "partial"]
    executable: Literal[False] = False
    notes: tuple[str, ...] = ()


class CounterfactualPlanSet(BaseModel):
    """Comparison artifact for composition decisions only."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    proposal_id: str = Field(min_length=1, max_length=80)
    plans: tuple[CounterfactualPlan, ...] = Field(min_length=1, max_length=4)
    selected_plan_id: str
    authority_class: Literal["read_model"] = "read_model"
    grants_execution_authority: Literal[False] = False


def _risk(actions: tuple[str, ...], record: MissionCompositionRecord) -> RiskLevel:
    effects = {item.side_effect_class for item in record.ability_selections if item.action_name in actions}
    if effects & {"external_send", "external_write", "external_publish"}:
        return "high"
    if effects & {"internal_write"}:
        return "medium"
    return "low"


def build_counterfactual_plan_set(record: MissionCompositionRecord) -> CounterfactualPlanSet:
    """Estimate the selected plan and a read-only projection deterministically."""

    selected_actions = tuple(step.action_name for step in record.planned_steps)
    selected_artifacts = tuple(step.output_contract for step in record.planned_steps)
    selected_effects = {
        item.action_name
        for item in record.ability_selections
        if item.side_effect_class in {"internal_write", "external_write", "external_send", "external_publish"}
    }
    read_only_actions = tuple(action for action in selected_actions if action not in selected_effects)
    read_only_artifacts = tuple(
        step.output_contract for step in record.planned_steps if step.action_name not in selected_effects
    )
    full_count = len(record.planned_steps)
    read_count = len(read_only_actions)
    selected = CounterfactualPlan(
        plan_id=f"{record.proposal_id}:selected",
        strategy="selected",
        action_names=selected_actions,
        expected_artifact_keys=selected_artifacts,
        evidence_score=1.0 if full_count else 0.0,
        estimated_cost_units=full_count,
        estimated_latency_units=max(1, full_count),
        risk_level=_risk(selected_actions, record),
        completeness="full" if record.ready_to_start else "partial",
        notes=("Estimate derived from the server-owned composition plan.",),
    )
    projection = CounterfactualPlan(
        plan_id=f"{record.proposal_id}:read-only",
        strategy="read_only_projection",
        action_names=read_only_actions,
        expected_artifact_keys=read_only_artifacts,
        evidence_score=(read_count / full_count) if full_count else 0.0,
        estimated_cost_units=read_count,
        estimated_latency_units=max(1, read_count),
        risk_level=_risk(read_only_actions, record),
        completeness="full" if read_count == full_count and record.ready_to_start else "partial",
        notes=(
            "Projection removes side-effecting actions for comparison only.",
            "Projection is not executable and cannot satisfy omitted side-effect outputs.",
        ),
    )
    return CounterfactualPlanSet(
        proposal_id=record.proposal_id,
        plans=(selected, projection),
        selected_plan_id=selected.plan_id,
    )
