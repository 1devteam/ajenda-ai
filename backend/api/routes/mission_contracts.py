from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.compliance import is_supported_compliance_category, is_supported_jurisdiction
from backend.services.mission_composition.deliverable_runtime_observability import (
    DeliverableRuntimeStateRead,
)

MissionPriority = Literal["low", "normal", "high", "urgent"]
MissionPlanningStatus = Literal["draft", "in_review", "approved", "rejected", "superseded"]
MissionRiskLevel = Literal["low", "medium", "high", "critical"]
MissionApprovalGateStatus = Literal["not_required", "required", "approved", "rejected"]
GraphMaterializationStatus = Literal["draft", "validated", "blocked", "approved", "superseded"]
GraphOperatorReviewStatus = Literal["not_required", "pending", "approved", "rejected", "changes_requested"]
GraphValidationStatus = Literal["not_run", "valid", "invalid", "warning"]
GraphValidationCheckStatus = Literal["passed", "warning", "failed"]
GraphGenerationMode = Literal["manual", "deterministic", "planner_assisted"]
RuntimeAdmissionStatus = Literal["draft", "validated", "admitted", "rejected", "superseded"]


class MissionSuccessCriterion(BaseModel):
    """A measurable outcome signal for mission completion."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    evidence: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("success criterion description is required")
        return value

    @field_validator("evidence")
    @classmethod
    def _normalize_evidence(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("success criterion evidence entries must be non-empty")
        return normalized


class MissionConstraint(BaseModel):
    """A mission intake constraint for future planning."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    hard: bool = True

    @field_validator("name", "description")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("constraint text fields must be non-empty")
        return value


class MissionBudgetLimits(BaseModel):
    """Optional budget/scope limits captured at intake without enforcing runtime dispatch."""

    model_config = ConfigDict(extra="forbid")

    max_tasks: int | None = Field(default=None, ge=1)
    max_runtime_minutes: int | None = Field(default=None, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _require_at_least_one_limit(self) -> MissionBudgetLimits:
        if self.max_tasks is None and self.max_runtime_minutes is None and self.max_cost_usd is None:
            raise ValueError("at least one budget limit is required when budget_limits is provided")
        return self


class MissionCreate(BaseModel):
    """Mission intake request accepted from tenant-authenticated callers."""

    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=5000)
    success_criteria: list[MissionSuccessCriterion] = Field(min_length=1, max_length=20)
    constraints: list[MissionConstraint] = Field(default_factory=list, max_length=20)
    operator_notes: str | None = Field(default=None, max_length=5000)
    context: dict[str, Any] = Field(default_factory=dict)
    priority: MissionPriority = "normal"
    approval_required: bool = False
    approval_expectations: list[str] = Field(default_factory=list, max_length=20)
    budget_limits: MissionBudgetLimits | None = None
    scope_limits: list[str] = Field(default_factory=list, max_length=20)
    allowed_actions: list[str] = Field(default_factory=list, max_length=50)
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    compliance_category: str = Field(default="operational", min_length=1, max_length=64)
    jurisdiction: str = Field(default="US-ALL", min_length=1, max_length=64)
    allow_legacy_v1: bool = False

    @field_validator("objective", "operator_notes", "compliance_category", "jurisdiction")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value

    @field_validator("compliance_category")
    @classmethod
    def _validate_compliance_category(cls, value: str) -> str:
        if not is_supported_compliance_category(value):
            raise ValueError("unsupported compliance_category")
        return value

    @field_validator("jurisdiction")
    @classmethod
    def _validate_jurisdiction(cls, value: str) -> str:
        if not is_supported_jurisdiction(value):
            raise ValueError("unsupported jurisdiction")
        return value

    @field_validator("approval_expectations", "scope_limits", "allowed_actions", "allowed_tools")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("list entries must be non-empty strings")
        if len(set(normalized)) != len(normalized):
            raise ValueError("list entries must be unique")
        return normalized


class MissionPlanStage(BaseModel):
    """A durable, operator-visible stage inside a mission plan phase."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    intent: str = Field(min_length=1, max_length=1000)
    desired_outputs: list[str] = Field(default_factory=list, max_length=20)
    capability_requirements: list[str] = Field(default_factory=list, max_length=20)
    approval_required: bool = False

    @field_validator("name", "intent")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("stage text fields must be non-empty")
        return value

    @field_validator("desired_outputs", "capability_requirements")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)


class MissionPlanPhase(BaseModel):
    """A planning phase; not a persisted DAG node and not runtime orchestration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=1000)
    stages: list[MissionPlanStage] = Field(default_factory=list, max_length=20)

    @field_validator("name", "objective")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("phase text fields must be non-empty")
        return value


class MissionDesiredOutput(BaseModel):
    """Expected mission output for later evidence/outcome review layers."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name", "description")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("desired output text fields must be non-empty")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def _normalize_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)


class MissionCapabilityRequirement(BaseModel):
    """Capability intent without enforcing a capability registry yet."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1, max_length=1000)
    required: bool = True
    risk_level: MissionRiskLevel = "medium"

    @field_validator("name", "purpose")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("capability requirement text fields must be non-empty")
        return value


class MissionApprovalGate(BaseModel):
    """Human/operator approval intent captured before future execution layers."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    required_before: str = Field(min_length=1, max_length=160)
    status: MissionApprovalGateStatus = "required"

    @field_validator("name", "description", "required_before")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("approval gate text fields must be non-empty")
        return value


class MissionEstimatedScope(BaseModel):
    """Estimated planning scope; advisory only and not quota enforcement."""

    model_config = ConfigDict(extra="forbid")

    estimated_tasks: int | None = Field(default=None, ge=1)
    estimated_runtime_minutes: int | None = Field(default=None, ge=1)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    complexity: Literal["low", "medium", "high", "unknown"] = "unknown"


class MissionRiskAnnotation(BaseModel):
    """Risk annotation for future governance/evidence layers."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    risk_level: MissionRiskLevel = "medium"
    mitigation: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "description", "mitigation")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("risk annotation text fields must be non-empty when provided")
        return value


class MissionPlanWrite(BaseModel):
    """Create/update mission plan contract; persistence only, never runtime dispatch."""

    model_config = ConfigDict(extra="forbid")

    planning_status: MissionPlanningStatus = "draft"
    phases: list[MissionPlanPhase] = Field(min_length=1, max_length=20)
    planning_notes: str | None = Field(default=None, max_length=5000)
    desired_outputs: list[MissionDesiredOutput] = Field(default_factory=list, max_length=50)
    capability_requirements: list[MissionCapabilityRequirement] = Field(default_factory=list, max_length=50)
    execution_strategy_hints: dict[str, Any] = Field(default_factory=dict)
    approval_gates: list[MissionApprovalGate] = Field(default_factory=list, max_length=50)
    operator_overrides: dict[str, Any] = Field(default_factory=dict)
    estimated_scope: MissionEstimatedScope = Field(default_factory=MissionEstimatedScope)
    risk_annotations: list[MissionRiskAnnotation] = Field(default_factory=list, max_length=50)

    @field_validator("planning_notes")
    @classmethod
    def _normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("planning notes must be non-empty when provided")
        return value


class MissionPlanStep(BaseModel):
    """Lightweight planned step contract; not a task graph node or execution task."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    depends_on: list[int] = Field(default_factory=list, max_length=50)
    expected_output: str = Field(min_length=1, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "description", "expected_output")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("planned step text fields must be non-empty")
        return value

    @field_validator("depends_on")
    @classmethod
    def _normalize_dependencies(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("planned step dependencies must be unique")
        return value

    @field_validator("metadata")
    @classmethod
    def _validate_json_safe_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            return cast(dict[str, Any], json.loads(json.dumps(value)))
        except (TypeError, ValueError) as exc:
            raise ValueError("planned step metadata must be JSON-safe") from exc


class MissionPlanCreate(BaseModel):
    """Durable mission planning contract request; persistence only, never execution."""

    model_config = ConfigDict(extra="forbid")

    objectives: list[str] = Field(default_factory=list, max_length=50)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=50)
    planned_steps: list[MissionPlanStep] = Field(default_factory=list, max_length=200)
    risk_notes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("objectives", "constraints", "assumptions", "acceptance_criteria", "risk_notes")
    @classmethod
    def _normalize_string_list(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _validate_step_dependencies(self) -> MissionPlanCreate:
        sequences = {step.sequence for step in self.planned_steps}
        if len(sequences) != len(self.planned_steps):
            raise ValueError("planned step sequences must be unique")
        for step in self.planned_steps:
            missing = [dependency for dependency in step.depends_on if dependency not in sequences]
            if missing:
                raise ValueError("planned step dependencies must reference existing sequences")
            if step.sequence in step.depends_on:
                raise ValueError("planned step cannot depend on itself")
        return self


class MissionTaskGraphRead(BaseModel):
    """Normalized task graph response stored on mission metadata."""

    schema_version: int
    mission_id: str | None = None
    graph_status: str
    graph_version: int | None = None
    graph_fingerprint: str | None = None
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    metadata: dict[str, Any]


class GraphPlannerProvenance(BaseModel):
    """Planner identity and input provenance for graph materialization."""

    model_config = ConfigDict(extra="forbid")

    planner_type: str = Field(min_length=1, max_length=120)
    planner_id: str | None = Field(default=None, max_length=160)
    planning_run_id: str | None = Field(default=None, max_length=160)
    plan_schema_version: int | None = Field(default=None, ge=1)
    inputs_checksum: str | None = Field(default=None, max_length=256)

    @field_validator("planner_type", "planner_id", "planning_run_id", "inputs_checksum")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "planner provenance text fields must be non-empty")


class GraphCapabilitySelectionProvenance(BaseModel):
    """Why a capability was selected for a planned graph node."""

    model_config = ConfigDict(extra="forbid")

    node_key: str = Field(min_length=1, max_length=160)
    capability_id: UUID | None = None
    capability_name: str | None = Field(default=None, min_length=1, max_length=160)
    capability_version: str | None = Field(default=None, min_length=1, max_length=64)
    selection_reason: str = Field(min_length=1, max_length=1000)
    selected_by: str | None = Field(default=None, max_length=160)
    alternatives_considered: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("node_key", "capability_name", "capability_version", "selection_reason", "selected_by")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "capability selection text fields must be non-empty")

    @field_validator("alternatives_considered")
    @classmethod
    def _normalize_alternatives(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _require_capability_identity(self) -> GraphCapabilitySelectionProvenance:
        if self.capability_id is None and self.capability_name is None:
            raise ValueError("capability selection requires capability_id or capability_name")
        return self


class GraphValidationCheck(BaseModel):
    """One structured graph validation check outcome."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    status: GraphValidationCheckStatus
    details: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "details")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "graph validation check text fields must be non-empty")


class GraphValidationResult(BaseModel):
    """Structured validation result for the generated graph contract."""

    model_config = ConfigDict(extra="forbid")

    validation_status: GraphValidationStatus
    summary: str = Field(min_length=1, max_length=2000)
    validated_at: datetime | None = None
    checks: list[GraphValidationCheck] = Field(default_factory=list, max_length=100)

    @field_validator("summary")
    @classmethod
    def _normalize_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("graph validation summary is required")
        return value


class GraphOperatorReview(BaseModel):
    """Operator approval/review state for materialized graph contracts."""

    model_config = ConfigDict(extra="forbid")

    status: GraphOperatorReviewStatus = "pending"
    reviewed_by: str | None = Field(default=None, max_length=160)
    reviewed_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("reviewed_by", "notes")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "operator review text fields must be non-empty")


class GraphGenerationMetadata(BaseModel):
    """How the graph contract was generated from planner output."""

    model_config = ConfigDict(extra="forbid")

    generator: str = Field(min_length=1, max_length=160)
    generation_mode: GraphGenerationMode = "deterministic"
    generated_at: datetime | None = None
    compiler_version: str | None = Field(default=None, max_length=64)
    source_plan_version: str | None = Field(default=None, max_length=64)
    deterministic_inputs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("generator", "compiler_version", "source_plan_version")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "graph generation text fields must be non-empty")


class DeterministicCompilationMetadata(BaseModel):
    """Compilation boundaries that make graph generation reproducible."""

    model_config = ConfigDict(extra="forbid")

    compiler_name: str = Field(min_length=1, max_length=160)
    compiler_version: str = Field(min_length=1, max_length=64)
    compilation_boundary: str = Field(default="planner_contract_to_task_graph_contract", min_length=1, max_length=160)
    input_fingerprint: str | None = Field(default=None, max_length=256)
    output_fingerprint: str | None = Field(default=None, max_length=256)
    deterministic: bool = True

    @field_validator(
        "compiler_name", "compiler_version", "compilation_boundary", "input_fingerprint", "output_fingerprint"
    )
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "deterministic compilation text fields must be non-empty")


class GraphMaterializationWrite(BaseModel):
    """Create/update planner-to-graph materialization metadata; never runtime execution."""

    model_config = ConfigDict(extra="forbid")

    materialization_status: GraphMaterializationStatus = "draft"
    materialization_source: str = Field(min_length=1, max_length=160)
    materialization_source_version: str = Field(min_length=1, max_length=64)
    planner_provenance: GraphPlannerProvenance
    capability_selection_provenance: list[GraphCapabilitySelectionProvenance] = Field(
        default_factory=list, max_length=200
    )
    graph_validation_result: GraphValidationResult
    operator_review: GraphOperatorReview = Field(default_factory=GraphOperatorReview)
    graph_generation_metadata: GraphGenerationMetadata
    deterministic_compilation_metadata: DeterministicCompilationMetadata
    generation_notes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("materialization_source", "materialization_source_version")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("materialization source fields must be non-empty")
        return value

    @field_validator("generation_notes")
    @classmethod
    def _normalize_notes(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)


class GraphMaterializationRead(BaseModel):
    """Graph materialization response envelope stored on mission metadata."""

    mission_id: UUID
    tenant_id: str
    materialization: dict[str, Any]
    updated_at: str


class RuntimeAdmissionNodeSelection(BaseModel):
    """One mission graph node selected for future runtime admission."""

    model_config = ConfigDict(extra="forbid")

    node_key: str = Field(min_length=1, max_length=160)
    runtime_task_type: str | None = Field(default=None, min_length=1, max_length=120)
    capability_id: UUID | None = None
    adapter_id: UUID | None = None
    operator_notes: str | None = Field(default=None, max_length=1000)

    @field_validator("node_key", "runtime_task_type", "operator_notes")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_non_empty_text(value, "runtime admission node fields must be non-empty")


class RuntimeAdmissionWrite(BaseModel):
    """Create/update graph-to-runtime admission metadata without queue authority.

    When selected_nodes is empty, the server derives selections from the compiled task graph
    after provisioning bridge capability/adapter authority. Client graph invent is not required.
    """

    model_config = ConfigDict(extra="forbid")

    admission_status: RuntimeAdmissionStatus = "admitted"
    admitted_by: str | None = Field(default=None, max_length=160)
    selected_nodes: list[RuntimeAdmissionNodeSelection] = Field(default_factory=list, max_length=200)
    auto_provision_authority: bool = True
    validation_notes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("admitted_by")
    @classmethod
    def _normalize_admitted_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("validation_notes")
    @classmethod
    def _normalize_validation_notes(cls, value: list[str]) -> list[str]:
        return _normalize_unique_string_list(value)

    @model_validator(mode="after")
    def _validate_unique_nodes(self) -> RuntimeAdmissionWrite:
        node_keys = [selection.node_key for selection in self.selected_nodes]
        if len(set(node_keys)) != len(node_keys):
            raise ValueError("runtime admission selected node keys must be unique")
        return self


class RuntimeAdmissionRead(BaseModel):
    """Runtime admission response envelope stored on mission metadata."""

    mission_id: UUID
    tenant_id: str
    runtime_admission: dict[str, Any]
    updated_at: str


class MissionPlanRead(BaseModel):
    """Mission plan response envelope for durable plans and legacy metadata plans."""

    mission_id: UUID
    tenant_id: str
    plan: dict[str, Any]
    updated_at: str
    plan_id: UUID | None = None
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class MissionRead(BaseModel):
    """Mission intake response contract."""

    mission_id: UUID
    tenant_id: str
    objective: str
    status: str
    compliance_category: str
    jurisdiction: str
    intake: dict[str, Any]
    deliverable_runtime_state: DeliverableRuntimeStateRead | None = None
    created_at: str
    updated_at: str


class MissionListItem(BaseModel):
    """Compact mission summary for tenant mission lists."""

    mission_id: UUID
    objective: str
    status: str
    scope_limits: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class MissionListResponse(BaseModel):
    """Tenant-scoped mission list envelope."""

    missions: list[MissionListItem]
    count: int
    total_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)


class MissionLifecycleCompleteness(BaseModel):
    """Contract-layer presence indicators for a mission lifecycle."""

    has_intake: bool
    has_plan: bool
    has_task_graph: bool
    has_materialization: bool
    has_runtime_admission: bool
    has_evidence: bool
    has_outcome_review: bool
    has_memory_promotions: bool
    has_retrieval_contracts: bool


class MissionLifecycleMissionSummary(BaseModel):
    """Compact mission identity and status for lifecycle reads."""

    mission_id: UUID
    tenant_id: str
    objective: str
    status: str
    compliance_category: str
    jurisdiction: str
    created_at: str
    updated_at: str


class MissionLifecycleEvidenceItem(BaseModel):
    """Compact evidence row included in the mission lifecycle read model."""

    evidence_id: UUID
    evidence_type: str
    evidence_source: str
    collection_status: str
    confidence: float | None
    created_at: str
    updated_at: str


class MissionLifecycleEvidenceSummary(BaseModel):
    """Evidence summary for the mission lifecycle read model."""

    count: int
    records: list[MissionLifecycleEvidenceItem]


class MissionLifecycleOutcomeReviewItem(BaseModel):
    """Compact outcome review row included in the mission lifecycle read model."""

    review_id: UUID
    review_status: str
    review_decision: str
    reviewer_type: str
    confidence: float | None
    created_at: str
    updated_at: str


class MissionLifecycleOutcomeReviewSummary(BaseModel):
    """Outcome review summary for the mission lifecycle read model."""

    count: int
    records: list[MissionLifecycleOutcomeReviewItem]


class MissionLifecycleMemoryPromotionSummary(BaseModel):
    """Memory promotion summary for the mission lifecycle read model."""

    count: int
    records: list[dict[str, Any]]


class MissionLifecycleRetrievalContractItem(BaseModel):
    """Compact retrieval contract row included in the mission lifecycle read model."""

    retrieval_id: UUID
    retrieval_strategy: str
    retrieval_status: str
    confidence: float | None
    created_at: str
    updated_at: str


class MissionLifecycleRetrievalContractSummary(BaseModel):
    """Retrieval contract summary for the mission lifecycle read model."""

    count: int
    records: list[MissionLifecycleRetrievalContractItem]


class MissionLifecycleRead(BaseModel):
    """Read-only aggregation of the mission product-layer lifecycle."""

    mission: MissionLifecycleMissionSummary
    intake: dict[str, Any] | None
    plan: dict[str, Any] | None
    task_graph: dict[str, Any] | None
    materialization: dict[str, Any] | None
    runtime_admission: dict[str, Any] | None
    evidence: MissionLifecycleEvidenceSummary
    outcome_reviews: MissionLifecycleOutcomeReviewSummary
    memory_promotions: MissionLifecycleMemoryPromotionSummary
    retrieval_contracts: MissionLifecycleRetrievalContractSummary
    completeness: MissionLifecycleCompleteness
    # Runtime ladder only (plan → admit). Empty means execution path is ready/done.
    missing_next_steps: list[str]
    # Optional product close-out (evidence review, outcome, memory, retrieval) — not pipeline failure.
    optional_closeout_steps: list[str] = Field(default_factory=list)


class MissionTimelineEvent(BaseModel):
    """Normalized read-only timeline event for mission explainability."""

    timestamp: str
    event_type: str
    stage: str
    source: str
    details: dict[str, Any] = Field(default_factory=dict)


class MissionTimelineRead(BaseModel):
    """Read-only mission timeline aggregation across mission/runtime/governance surfaces."""

    mission_id: UUID
    tenant_id: str
    authority_class: Literal["read_model"] = "read_model"
    side_effect_class: Literal["none"] = "none"
    does_not_execute_runtime_work: bool = True
    events: list[MissionTimelineEvent]


class MissionQueueResponse(BaseModel):
    queued_task_ids: list[str]
    pending_review_task_ids: list[str]
    denied_tasks: list[dict[str, str | None]]


class RuntimeQueueAdmissionResponse(MissionQueueResponse):
    """Queue admission response for current materialized runtime tasks."""

    admission_status: str
    admitted_task_ids: list[str]
    blocked_task_ids: list[str]
    blockers: list[dict[str, Any]]
    runtime_queue_admission: dict[str, Any]


class BridgeRuntimeAuthorityNode(BaseModel):
    """Capability/adapter authority provisioned for one mission graph node."""

    node_key: str
    action: str
    capability_id: str
    adapter_id: str
    capability_name: str


class BridgeRuntimeAuthorityRead(BaseModel):
    """Response envelope for mission bridge runtime authority provisioning."""

    mission_id: UUID
    tenant_id: str
    node_authorities: list[BridgeRuntimeAuthorityNode]


def _normalize_unique_string_list(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("list entries must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("list entries must be unique")
    return normalized


def _normalize_optional_non_empty_text(value: str | None, message: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError(message)
    return value


class MissionCompileRequest(BaseModel):
    """Client may supply intent only — never a client-built graph."""

    model_config = ConfigDict(extra="forbid")

    instruction: str | None = Field(default=None, max_length=8000)
    persist: bool = True
    source: str = Field(default="mission_compile", min_length=1, max_length=80)


class MissionCompileResponse(BaseModel):
    """Server-owned compile package for an existing mission."""

    model_config = ConfigDict(extra="forbid")

    compiler: dict[str, Any]
    mission_id: str
    proposal_id: str
    compile_status: str
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any]
    task_graph: dict[str, Any]
    binding_manifest: list[dict[str, Any]] = Field(default_factory=list)
    required_credentials: list[dict[str, Any]] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)
    side_effect_summary: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any]
    display: dict[str, Any]
    persisted: bool
    grants_execution_authority: bool = False
    runtime_queued: bool = False
    next_steps: list[str] = Field(default_factory=list)


class MissionLaunchResponse(BaseModel):
    """Receipt for the explicit compile-to-queue mission launch orchestration."""

    model_config = ConfigDict(extra="forbid")

    mission_id: UUID
    compile_status: str
    graph_materialized: bool
    runtime_admitted: bool
    runtime_tasks_materialized: int
    queued_task_ids: list[str]
    pending_review_task_ids: list[str]
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    idempotency_key: str | None = None


class MissionCancelRequest(BaseModel):
    reason: str = Field(default="Stopped by operator", min_length=1, max_length=500)


__all__ = [
    "BridgeRuntimeAuthorityNode",
    "BridgeRuntimeAuthorityRead",
    "DeterministicCompilationMetadata",
    "GraphCapabilitySelectionProvenance",
    "GraphGenerationMetadata",
    "GraphGenerationMode",
    "GraphMaterializationRead",
    "GraphMaterializationStatus",
    "GraphMaterializationWrite",
    "GraphOperatorReview",
    "GraphOperatorReviewStatus",
    "GraphPlannerProvenance",
    "GraphValidationCheck",
    "GraphValidationCheckStatus",
    "GraphValidationResult",
    "GraphValidationStatus",
    "MissionApprovalGate",
    "MissionApprovalGateStatus",
    "MissionBudgetLimits",
    "MissionCancelRequest",
    "MissionCapabilityRequirement",
    "MissionCompileRequest",
    "MissionCompileResponse",
    "MissionConstraint",
    "MissionCreate",
    "MissionDesiredOutput",
    "MissionEstimatedScope",
    "MissionLaunchResponse",
    "MissionLifecycleCompleteness",
    "MissionLifecycleEvidenceItem",
    "MissionLifecycleEvidenceSummary",
    "MissionLifecycleMemoryPromotionSummary",
    "MissionLifecycleMissionSummary",
    "MissionLifecycleOutcomeReviewItem",
    "MissionLifecycleOutcomeReviewSummary",
    "MissionLifecycleRead",
    "MissionLifecycleRetrievalContractItem",
    "MissionLifecycleRetrievalContractSummary",
    "MissionListItem",
    "MissionListResponse",
    "MissionPlanCreate",
    "MissionPlanPhase",
    "MissionPlanRead",
    "MissionPlanStage",
    "MissionPlanStep",
    "MissionPlanWrite",
    "MissionPlanningStatus",
    "MissionPriority",
    "MissionQueueResponse",
    "MissionRead",
    "MissionRiskAnnotation",
    "MissionRiskLevel",
    "MissionSuccessCriterion",
    "MissionTaskGraphRead",
    "MissionTimelineEvent",
    "MissionTimelineRead",
    "RuntimeAdmissionNodeSelection",
    "RuntimeAdmissionRead",
    "RuntimeAdmissionStatus",
    "RuntimeAdmissionWrite",
    "RuntimeQueueAdmissionResponse",
]
