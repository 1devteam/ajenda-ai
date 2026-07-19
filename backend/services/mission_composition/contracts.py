"""Mission Composition Engine contracts (ADR-0008).

These models describe interpretation and planning only. They do not grant
runtime execution authority, queue work, claim leases, or invoke tools.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COMPOSITION_SCHEMA_VERSION = 1
JOB_CATALOG_VERSION = "1"
INTERPRETER_VERSION = "1"
CAPABILITY_RESOLVER_VERSION = "1"

JobRiskLevel = Literal["low", "medium", "high", "critical"]
JobMaturity = Literal["runtime_bound", "catalog_only"]
ReadinessStatus = Literal[
    "ready",
    "connection_required",
    "charter_blocked",
    "catalog_only",
    "unavailable",
    "permission_required",
]
SelectionStatus = Literal["selected", "alternative", "rejected"]


class TargetEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=80)
    industry: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=240)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)


class SuccessCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    measurable: bool = True


class BudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tasks: int | None = Field(default=None, ge=1)
    max_runtime_minutes: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)


class MissionIntent(BaseModel):
    """Candidate interpretation of a user instruction. Not an execution grant."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=5000)
    requested_outcomes: list[str] = Field(default_factory=list, max_length=30)
    target_entities: list[TargetEntity] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    forbidden_outcomes: list[str] = Field(default_factory=list, max_length=30)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list, max_length=20)
    urgency: str = Field(default="normal", max_length=40)
    approval_preference: str = Field(default="review_before_external_action", max_length=80)
    budget_limits: BudgetLimits | None = None
    context_requirements: list[str] = Field(default_factory=list, max_length=20)
    ambiguity: list[Clarification] = Field(default_factory=list, max_length=20)
    interpreter_version: str = Field(default=INTERPRETER_VERSION, max_length=40)

    @field_validator(
        "requested_outcomes",
        "constraints",
        "forbidden_outcomes",
        "context_requirements",
    )
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item and item.strip()]
        if len(set(normalized)) != len(normalized):
            raise ValueError("list entries must be unique")
        return normalized


class BusinessJob(BaseModel):
    """Business work unit between intent outcomes and governed abilities."""

    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    vertical_role: str = Field(min_length=1, max_length=120)
    supported_outcomes: tuple[str, ...] = ()
    required_inputs: tuple[str, ...] = ()
    produced_outputs: tuple[str, ...] = ()
    candidate_actions: tuple[str, ...] = ()
    risk_level: JobRiskLevel = "low"
    maturity: JobMaturity = "runtime_bound"
    credential_policy: Literal["none", "optional", "required"] = "none"
    approval_policy: Literal["none", "review_before_external", "always_review"] = "none"
    evidence_requirements: tuple[str, ...] = ()
    depends_on_jobs: tuple[str, ...] = ()
    seed_brain_missions: tuple[str, ...] = ()


class AbilityAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=160)
    status: ReadinessStatus
    reason_not_selected: str | None = Field(default=None, max_length=500)


class AbilitySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    ability_id: str | None = Field(default=None, max_length=160)
    action_name: str = Field(min_length=1, max_length=160)
    selection_status: SelectionStatus = "selected"
    selection_reason: str = Field(min_length=1, max_length=500)
    readiness: ReadinessStatus
    vertical_role: str = Field(min_length=1, max_length=120)
    alternatives: list[AbilityAlternative] = Field(default_factory=list, max_length=20)
    credential_reference: dict[str, Any] | None = None
    side_effect_class: str = Field(min_length=1, max_length=40)
    requires_connection: bool = False
    connection_provider: str | None = Field(default=None, max_length=80)


class JobAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    vertical_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    depends_on_jobs: list[str] = Field(default_factory=list, max_length=20)


class PlannedStepPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=1)
    job_key: str = Field(min_length=1, max_length=120)
    action_name: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1000)
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    output_contract: str = Field(min_length=1, max_length=240)
    input_bindings: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    tool_input: dict[str, Any] = Field(default_factory=dict)
    credential_reference: dict[str, Any] | None = None


class AllowedActionsProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_by: Literal["mission_composition_engine"] = "mission_composition_engine"
    selection_version: str = Field(default="1", max_length=40)
    user_supplied: Literal[False] = False
    validated_against_registry: bool = True
    validated_against_charter: bool = True
    validated_against_manifests: bool = True
    job_catalog_version: str = Field(default=JOB_CATALOG_VERSION, max_length=40)
    resolver_version: str = Field(default=CAPABILITY_RESOLVER_VERSION, max_length=40)


class CompositionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpreter_version: str = Field(default=INTERPRETER_VERSION, max_length=40)
    job_catalog_version: str = Field(default=JOB_CATALOG_VERSION, max_length=40)
    resolver_version: str = Field(default=CAPABILITY_RESOLVER_VERSION, max_length=40)
    composition_schema_version: int = Field(default=COMPOSITION_SCHEMA_VERSION, ge=1)
    grants_execution_authority: Literal[False] = False
    authority_class: Literal["declarative", "read_model"] = "read_model"


class MissionCompositionRecord(BaseModel):
    """Canonical per-mission composition artifact before runtime admission."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=COMPOSITION_SCHEMA_VERSION, ge=1)
    proposal_id: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=8000)
    intent: MissionIntent
    job_assignments: list[JobAssignment] = Field(default_factory=list, max_length=40)
    ability_selections: list[AbilitySelection] = Field(default_factory=list, max_length=40)
    forbidden_actions: list[str] = Field(default_factory=list, max_length=40)
    allowed_actions: list[str] = Field(default_factory=list, max_length=50)
    allowed_actions_provenance: AllowedActionsProvenance = Field(default_factory=AllowedActionsProvenance)
    missing_connections: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    approval_gates: list[str] = Field(default_factory=list, max_length=20)
    planned_steps: list[PlannedStepPreview] = Field(default_factory=list, max_length=40)
    task_graph_preview: dict[str, Any] = Field(default_factory=dict)
    clarifications: list[Clarification] = Field(default_factory=list, max_length=20)
    ready_to_start: bool = False
    composition_provenance: CompositionProvenance = Field(default_factory=CompositionProvenance)

    @model_validator(mode="after")
    def _selected_actions_subset(self) -> MissionCompositionRecord:
        runtime_selected = sorted(
            {
                item.action_name
                for item in self.ability_selections
                if item.selection_status == "selected" and item.readiness == "ready"
            }
        )
        if list(self.allowed_actions) != runtime_selected and self.ability_selections:
            self.allowed_actions = runtime_selected
        return self
