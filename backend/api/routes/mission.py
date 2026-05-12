from __future__ import annotations

import hashlib
import json
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_PLAN_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY,
    MISSION_RUNTIME_QUEUE_ADMISSION_SCHEMA_VERSION,
    MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    Mission,
    build_graph_materialization_metadata,
    build_mission_intake_metadata,
    build_mission_plan_metadata,
    build_mission_task_graph_metadata,
    build_runtime_admission_metadata,
)
from backend.queue.base import QueueAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.outcome_review_repository import OutcomeReviewRepository
from backend.repositories.retrieval_contract_repository import RetrievalContractRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_executor import MissionExecutor
from backend.services.mission_runtime_projection import (
    build_execution_task_payload,
    build_runtime_task_materialization_metadata,
    materialization_reference_current,
    runtime_materialization_authority_flags,
    runtime_preview_authority_flags,
    supersede_runtime_task_materialization,
)
from backend.services.mission_runtime_projection import (
    build_runtime_task_preview_items as project_runtime_task_preview_items,
)
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/missions", tags=["missions"])

MissionPriority = Literal["low", "normal", "high", "urgent"]
MissionPlanningStatus = Literal["draft", "in_review", "approved", "rejected", "superseded"]
MissionRiskLevel = Literal["low", "medium", "high", "critical"]
MissionApprovalGateStatus = Literal["not_required", "required", "approved", "rejected"]
MissionTaskGraphStatus = Literal["draft", "in_review", "approved", "rejected", "superseded"]
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

    @field_validator("objective", "operator_notes", "compliance_category", "jurisdiction")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
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


class MissionTaskGraphCapabilityReference(BaseModel):
    """Capability reference for a planned graph node; declaration only."""

    model_config = ConfigDict(extra="forbid")

    capability_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    version: str | None = Field(default=None, min_length=1, max_length=64)
    purpose: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "version", "purpose")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("capability reference text fields must be non-empty when provided")
        return value

    @model_validator(mode="after")
    def _require_reference_identity(self) -> MissionTaskGraphCapabilityReference:
        if self.capability_id is None and self.name is None:
            raise ValueError("capability reference requires capability_id or name")
        return self


class MissionTaskGraphNode(BaseModel):
    """A planned work node; not an ExecutionTask and not dispatchable yet."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    intended_task_type: str = Field(min_length=1, max_length=120)
    capability_references: list[MissionTaskGraphCapabilityReference] = Field(default_factory=list, max_length=20)
    input_contract: dict[str, Any] = Field(default_factory=dict)
    expected_output_contract: dict[str, Any] = Field(default_factory=dict)
    risk_level: MissionRiskLevel = "medium"
    approval_required: bool = False
    execution_constraints: dict[str, Any] = Field(default_factory=dict)
    operator_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("key", "name", "intended_task_type", "operator_notes")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("task graph node text fields must be non-empty when provided")
        return value


class MissionTaskGraphEdge(BaseModel):
    """A dependency edge from prerequisite node to dependent node."""

    model_config = ConfigDict(extra="forbid")

    from_node_key: str = Field(min_length=1, max_length=160)
    to_node_key: str = Field(min_length=1, max_length=160)
    dependency_type: str = Field(default="depends_on", min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("from_node_key", "to_node_key", "dependency_type", "description")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("task graph edge text fields must be non-empty when provided")
        return value


class MissionTaskGraphWrite(BaseModel):
    """Create/update task graph contract; persistence only, never runtime dispatch."""

    model_config = ConfigDict(extra="forbid")

    graph_status: MissionTaskGraphStatus = "draft"
    nodes: list[MissionTaskGraphNode] = Field(min_length=1, max_length=200)
    edges: list[MissionTaskGraphEdge] = Field(default_factory=list, max_length=1000)
    operator_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("operator_notes")
    @classmethod
    def _normalize_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("task graph operator notes must be non-empty when provided")
        return value

    @model_validator(mode="after")
    def _validate_graph_shape(self) -> MissionTaskGraphWrite:
        node_keys = [node.key for node in self.nodes]
        if len(set(node_keys)) != len(node_keys):
            raise ValueError("task graph node keys must be unique")

        node_key_set = set(node_keys)
        adjacency: dict[str, list[str]] = {key: [] for key in node_keys}
        for edge in self.edges:
            if edge.from_node_key not in node_key_set or edge.to_node_key not in node_key_set:
                raise ValueError("task graph edges must reference existing node keys")
            if edge.from_node_key == edge.to_node_key:
                raise ValueError("task graph edges cannot point a node to itself")
            adjacency[edge.from_node_key].append(edge.to_node_key)

        visiting: set[str] = set()
        visited: set[str] = set()

        def _visit(key: str) -> None:
            if key in visiting:
                raise ValueError("task graph must be acyclic")
            if key in visited:
                return
            visiting.add(key)
            for dependent_key in adjacency[key]:
                _visit(dependent_key)
            visiting.remove(key)
            visited.add(key)

        for key in node_keys:
            _visit(key)
        return self


class MissionTaskGraphRead(BaseModel):
    """Task graph response envelope stored on mission metadata."""

    mission_id: UUID
    tenant_id: str
    task_graph: dict[str, Any]
    updated_at: str


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
    """Create/update graph-to-runtime admission metadata without queue authority."""

    model_config = ConfigDict(extra="forbid")

    admission_status: RuntimeAdmissionStatus = "validated"
    admitted_by: str = Field(min_length=1, max_length=160)
    selected_nodes: list[RuntimeAdmissionNodeSelection] = Field(min_length=1, max_length=200)
    validation_notes: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("admitted_by")
    @classmethod
    def _normalize_admitted_by(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("admitted_by is required")
        return value

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


RuntimeReadinessStatus = Literal["ready", "blocked", "incomplete"]
RuntimeReadinessCheckStatus = Literal["passed", "warning", "failed"]


class RuntimeReadinessItem(BaseModel):
    """One deterministic runtime readiness check, blocker, or warning."""

    code: str
    status: RuntimeReadinessCheckStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeReadinessRead(BaseModel):
    """Read-only runtime admission readiness validation result."""

    mission_id: UUID
    tenant_id: str
    ready: bool
    readiness_status: RuntimeReadinessStatus
    checked_at: str
    graph_reference: dict[str, Any] | None
    materialization_reference: dict[str, Any] | None
    admission_reference: dict[str, Any] | None
    selected_node_count: int
    checks: list[RuntimeReadinessItem]
    blockers: list[RuntimeReadinessItem]
    warnings: list[RuntimeReadinessItem]


RuntimeTaskPreviewStatus = Literal["ready", "blocked", "incomplete"]


class RuntimeTaskPreviewPayload(BaseModel):
    """Deterministic, non-persisted payload envelope preview for a future task."""

    mission_id: UUID
    graph_node_key: str
    graph_version: int | None
    graph_fingerprint: str | None
    materialization_version: int | None
    admission_version: int | None
    runtime_task_type: str
    input_contract: dict[str, Any]
    expected_output_contract: dict[str, Any]
    execution_constraints: dict[str, Any]


class RuntimeTaskPreviewItem(BaseModel):
    """One future ExecutionTask row preview; never persisted by this endpoint."""

    preview_task_key: str
    graph_node_key: str
    graph_node_name: str | None
    runtime_task_type: str
    future_execution_task_state: Literal["planned"] = "planned"
    payload_preview: RuntimeTaskPreviewPayload
    capability_reference: dict[str, Any] | None
    adapter_reference: dict[str, Any] | None
    materialization_selection_reference: dict[str, Any] | None
    dependency_keys: list[str]
    operator_notes: str | None


class RuntimeTaskPreviewRead(BaseModel):
    """Read-only preview of future runtime task materialization."""

    mission_id: UUID
    tenant_id: str
    ready: bool
    preview_status: RuntimeTaskPreviewStatus
    checked_at: str
    readiness_summary: dict[str, Any]
    task_count: int
    tasks: list[RuntimeTaskPreviewItem]
    blockers: list[RuntimeReadinessItem]
    warnings: list[RuntimeReadinessItem]
    runtime_authority: dict[str, bool]


RuntimeTaskMaterializationStatus = Literal["materialized", "blocked", "superseded"]
RuntimeDispatchReadinessStatus = Literal["ready", "partial", "blocked"]


class RuntimeTaskMaterializationRead(BaseModel):
    """ExecutionTask materialization response envelope for a mission graph admission."""

    mission_id: UUID
    tenant_id: str
    materialization_status: RuntimeTaskMaterializationStatus
    materialization_version: int | None
    created_execution_task_ids: list[UUID]
    task_count: int
    graph_reference: dict[str, Any] | None
    materialization_reference: dict[str, Any] | None
    admission_reference: dict[str, Any] | None
    runtime_authority: dict[str, bool]
    blockers: list[RuntimeReadinessItem]
    warnings: list[RuntimeReadinessItem]
    updated_at: str


class RuntimeDispatchAuthority(BaseModel):
    """Negative authority flags for read-only dispatch readiness checks."""

    creates_execution_tasks: bool = False
    enqueues_work: bool = False
    dispatches_workers: bool = False
    calls_executor: bool = False
    calls_coordinator: bool = False
    executes_adapters: bool = False
    read_only: bool = True


class RuntimeDispatchReadinessRead(BaseModel):
    """Read-only readiness view for queued materialized task dispatch."""

    mission_id: UUID
    tenant_id: str
    readiness_status: RuntimeDispatchReadinessStatus
    dispatch_ready_task_ids: list[str]
    not_ready_task_ids: list[str]
    blocked_task_ids: list[str]
    skipped_task_ids: list[str]
    task_count: int
    queued_task_count: int
    materialization_reference: dict[str, Any] | None
    queue_admission_reference: dict[str, Any] | None
    runtime_authority: RuntimeDispatchAuthority
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    checked_at: str


class MissionPlanRead(BaseModel):
    """Mission plan response envelope stored on the mission metadata."""

    mission_id: UUID
    tenant_id: str
    plan: dict[str, Any]
    updated_at: str


class MissionRead(BaseModel):
    """Mission intake response contract."""

    mission_id: UUID
    tenant_id: str
    objective: str
    status: str
    compliance_category: str
    jurisdiction: str
    intake: dict[str, Any]
    created_at: str
    updated_at: str


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
    missing_next_steps: list[str]


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


def _task_graph_fingerprint(
    *,
    mission_id: str,
    graph_status: str | None,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    operator_notes: str | None,
) -> str:
    graph_identity = {
        "schema_version": 1,
        "mission_id": mission_id,
        "graph_status": graph_status,
        "nodes": nodes,
        "edges": edges,
        "operator_notes": operator_notes,
    }
    encoded = json.dumps(graph_identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _fingerprint_existing_task_graph(task_graph: dict[str, Any]) -> str | None:
    nodes = task_graph.get("nodes")
    edges = task_graph.get("edges")
    mission_id = task_graph.get("mission_id")
    if not isinstance(nodes, list) or not isinstance(edges, list) or not isinstance(mission_id, str):
        return None
    if not all(isinstance(node, dict) for node in nodes) or not all(isinstance(edge, dict) for edge in edges):
        return None
    return _task_graph_fingerprint(
        mission_id=mission_id,
        graph_status=task_graph.get("graph_status") if isinstance(task_graph.get("graph_status"), str) else None,
        nodes=nodes,
        edges=edges,
        operator_notes=task_graph.get("operator_notes") if isinstance(task_graph.get("operator_notes"), str) else None,
    )


def _next_task_graph_version(existing_graph: Any) -> int:
    if not isinstance(existing_graph, dict):
        return 1
    version = existing_graph.get("graph_version")
    if not isinstance(version, int) or version < 1:
        return 1
    return version + 1


def _supersede_graph_materialization(
    *,
    metadata: dict[str, Any],
    graph_version: int,
    graph_fingerprint: str,
    updated_at: str,
) -> None:
    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        return
    superseded = dict(materialization)
    superseded["materialization_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "task_graph_replaced"
    superseded["superseded_by_graph_version"] = graph_version
    superseded["superseded_by_graph_fingerprint"] = graph_fingerprint
    metadata[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY] = superseded


def _supersede_runtime_admission(
    *,
    metadata: dict[str, Any],
    graph_version: int,
    graph_fingerprint: str,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "task_graph_replaced"
    superseded["superseded_by_graph_version"] = graph_version
    superseded["superseded_by_graph_fingerprint"] = graph_fingerprint
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded


def _supersede_runtime_admission_for_materialization(
    *,
    metadata: dict[str, Any],
    materialization_version: int,
    updated_at: str,
) -> None:
    admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    if not isinstance(admission, dict):
        return
    superseded = dict(admission)
    superseded["admission_status"] = "superseded"
    superseded["updated_at"] = updated_at
    superseded["superseded_at"] = updated_at
    superseded["superseded_reason"] = "graph_materialization_replaced"
    superseded["superseded_by_materialization_version"] = materialization_version
    metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = superseded


def _runtime_admission_to_read(mission: Mission) -> RuntimeAdmissionRead:
    return RuntimeAdmissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        runtime_admission=mission.metadata_json.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _cancel_superseded_materialized_planned_tasks(
    *, metadata: dict[str, Any], task_repo: ExecutionTaskRepository, tenant_id: str, mission_id: UUID
) -> list[str]:
    """Cancel planned ExecutionTask rows referenced by active runtime task materialization metadata."""
    task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(task_materialization, dict):
        return []
    raw_task_ids = task_materialization.get("created_execution_task_ids")
    if not isinstance(raw_task_ids, list):
        return []
    task_ids: list[UUID] = []
    for raw_task_id in raw_task_ids:
        try:
            task_ids.append(UUID(str(raw_task_id)))
        except ValueError:
            continue
    cancelled_tasks = task_repo.cancel_planned_by_ids_for_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=task_ids
    )
    return [str(task.id) for task in cancelled_tasks]


def _current_materialized_execution_task_ids(metadata: dict[str, Any]) -> list[UUID]:
    """Return valid task IDs from the current runtime task materialization metadata."""
    task_materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(task_materialization, dict):
        return []
    if task_materialization.get("materialization_status") != "materialized":
        return []
    raw_task_ids = task_materialization.get("created_execution_task_ids")
    if not isinstance(raw_task_ids, list):
        return []

    task_ids: list[UUID] = []
    seen_task_ids: set[UUID] = set()
    for raw_task_id in raw_task_ids:
        try:
            task_id = UUID(str(raw_task_id))
        except ValueError:
            continue
        if task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)
        task_ids.append(task_id)
    return task_ids


def _readiness_item(
    *, code: str, status: RuntimeReadinessCheckStatus, message: str, details: dict[str, Any] | None = None
) -> RuntimeReadinessItem:
    return RuntimeReadinessItem(code=code, status=status, message=message, details=details or {})


def _runtime_readiness_reference(metadata: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    value = (metadata or {}).get(key)
    if isinstance(value, dict):
        return value
    return None


def _graph_matches_reference(*, task_graph: dict[str, Any], graph_reference: dict[str, Any] | None) -> bool:
    graph_fingerprint = task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph)
    return isinstance(graph_reference, dict) and (
        graph_reference.get("metadata_key") == MISSION_TASK_GRAPH_METADATA_KEY
        and graph_reference.get("graph_version") == task_graph.get("graph_version")
        and graph_reference.get("graph_fingerprint") == graph_fingerprint
    )


def _materialization_matches_reference(
    *, materialization: dict[str, Any], materialization_reference: dict[str, Any] | None
) -> bool:
    if not isinstance(materialization_reference, dict):
        return False
    return (
        materialization_reference.get("metadata_key") == MISSION_GRAPH_MATERIALIZATION_METADATA_KEY
        and materialization_reference.get("materialization_status") == materialization.get("materialization_status")
        and materialization_reference.get("materialization_version") == materialization.get("materialization_version")
        and materialization_reference.get("graph_reference") == materialization.get("graph_reference")
    )


def _resolve_capability_for_readiness(
    *,
    selected_node: dict[str, Any],
    graph_node: dict[str, Any],
    capability_repo: CapabilityRepository,
    tenant_id: str,
    blockers: list[RuntimeReadinessItem],
    checks: list[RuntimeReadinessItem],
) -> tuple[_uuid.UUID | None, str | None, str | None]:
    capability_id: _uuid.UUID | None = None
    raw_capability_id = selected_node.get("capability_id")
    if isinstance(raw_capability_id, str) and raw_capability_id.strip():
        try:
            capability_id = _uuid.UUID(raw_capability_id)
        except ValueError:
            blockers.append(
                _readiness_item(
                    code="capability_not_visible",
                    status="failed",
                    message="Selected node capability_id is not a valid UUID.",
                    details={"node_key": selected_node.get("node_key"), "capability_id": raw_capability_id},
                )
            )
            return None, None, None

    capability_name: str | None = None
    capability_version: str | None = None
    materialization_selection = selected_node.get("materialization_selection_reference")
    if isinstance(materialization_selection, dict):
        raw_name = materialization_selection.get("capability_name")
        raw_version = materialization_selection.get("capability_version")
        if isinstance(raw_name, str) and raw_name.strip():
            capability_name = raw_name.strip()
        if isinstance(raw_version, str) and raw_version.strip():
            capability_version = raw_version.strip()

    raw_capability_refs = graph_node.get("capability_references")
    capability_refs: list[Any] = raw_capability_refs if isinstance(raw_capability_refs, list) else []
    if capability_id is None:
        for capability_ref in capability_refs:
            if not isinstance(capability_ref, dict):
                continue
            raw_ref_id = capability_ref.get("capability_id")
            if isinstance(raw_ref_id, str) and raw_ref_id.strip():
                try:
                    capability_id = _uuid.UUID(raw_ref_id)
                except ValueError:
                    blockers.append(
                        _readiness_item(
                            code="capability_not_visible",
                            status="failed",
                            message="Task graph capability_id is not a valid UUID.",
                            details={"node_key": selected_node.get("node_key"), "capability_id": raw_ref_id},
                        )
                    )
                    return None, None, None
                break
            if (
                capability_name is None
                and isinstance(capability_ref.get("name"), str)
                and capability_ref["name"].strip()
            ):
                capability_name = capability_ref["name"].strip()
            if (
                capability_version is None
                and isinstance(capability_ref.get("version"), str)
                and capability_ref["version"].strip()
            ):
                capability_version = capability_ref["version"].strip()

    if capability_id is not None:
        capability = capability_repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id)
        if capability is None:
            blockers.append(
                _readiness_item(
                    code="capability_not_visible",
                    status="failed",
                    message="Selected node capability is no longer visible to the tenant.",
                    details={"node_key": selected_node.get("node_key"), "capability_id": str(capability_id)},
                )
            )
            return capability_id, capability_name, capability_version
        checks.append(
            _readiness_item(
                code="capability_visible",
                status="passed",
                message="Selected node capability is tenant-visible.",
                details={"node_key": selected_node.get("node_key"), "capability_id": str(capability_id)},
            )
        )
        return (
            capability_id,
            getattr(capability, "name", capability_name),
            getattr(capability, "version", capability_version),
        )

    if capability_name and capability_version:
        capability = capability_repo.get_conflict_for_scope(
            name=capability_name,
            version=capability_version,
            tenant_id=tenant_id,
        )
        if capability is None:
            capability = capability_repo.get_conflict_for_scope(
                name=capability_name,
                version=capability_version,
                tenant_id=None,
            )
        if capability is not None:
            checks.append(
                _readiness_item(
                    code="capability_visible",
                    status="passed",
                    message="Selected node capability name/version is tenant-visible.",
                    details={
                        "node_key": selected_node.get("node_key"),
                        "capability_name": capability_name,
                        "capability_version": capability_version,
                    },
                )
            )
            return getattr(capability, "id", None), capability_name, capability_version

    blockers.append(
        _readiness_item(
            code="capability_not_visible",
            status="failed",
            message="Selected node capability reference is no longer tenant-visible.",
            details={
                "node_key": selected_node.get("node_key"),
                "capability_name": capability_name,
                "capability_version": capability_version,
            },
        )
    )
    return capability_id, capability_name, capability_version


def _validate_adapter_for_readiness(
    *,
    selected_node: dict[str, Any],
    admitted_capability_id: _uuid.UUID | None,
    admitted_capability_name: str | None,
    admitted_capability_version: str | None,
    adapter_repo: CapabilityAdapterRepository,
    tenant_id: str,
    blockers: list[RuntimeReadinessItem],
    checks: list[RuntimeReadinessItem],
) -> None:
    raw_adapter_id = selected_node.get("adapter_id")
    if raw_adapter_id is None:
        return
    if not isinstance(raw_adapter_id, str) or not raw_adapter_id.strip():
        blockers.append(
            _readiness_item(
                code="adapter_not_visible",
                status="failed",
                message="Selected node adapter_id is invalid.",
                details={"node_key": selected_node.get("node_key"), "adapter_id": raw_adapter_id},
            )
        )
        return
    try:
        adapter_id = _uuid.UUID(raw_adapter_id)
    except ValueError:
        blockers.append(
            _readiness_item(
                code="adapter_not_visible",
                status="failed",
                message="Selected node adapter_id is not a valid UUID.",
                details={"node_key": selected_node.get("node_key"), "adapter_id": raw_adapter_id},
            )
        )
        return

    adapter = adapter_repo.get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id)
    if adapter is None:
        blockers.append(
            _readiness_item(
                code="adapter_not_visible",
                status="failed",
                message="Selected node adapter is no longer visible to the tenant.",
                details={"node_key": selected_node.get("node_key"), "adapter_id": str(adapter_id)},
            )
        )
        return

    adapter_capability_id = getattr(adapter, "capability_id", None)
    adapter_capability_name = getattr(adapter, "capability_name", None)
    adapter_capability_version = getattr(adapter, "capability_version", None)

    mismatch_details = {
        "node_key": selected_node.get("node_key"),
        "adapter_id": str(adapter_id),
        "adapter_capability_id": str(adapter_capability_id) if adapter_capability_id is not None else None,
        "adapter_capability_name": adapter_capability_name,
        "adapter_capability_version": adapter_capability_version,
        "admitted_capability_id": str(admitted_capability_id) if admitted_capability_id is not None else None,
        "admitted_capability_name": admitted_capability_name,
        "admitted_capability_version": admitted_capability_version,
    }

    id_binding_matches = (
        adapter_capability_id is not None
        and admitted_capability_id is not None
        and adapter_capability_id == admitted_capability_id
    )
    name_binding_matches = (
        adapter_capability_name is not None
        and admitted_capability_name is not None
        and adapter_capability_name == admitted_capability_name
        and (
            adapter_capability_version is None
            or admitted_capability_version is None
            or adapter_capability_version == admitted_capability_version
        )
    )

    if not id_binding_matches and not name_binding_matches:
        blockers.append(
            _readiness_item(
                code="adapter_capability_mismatch",
                status="failed",
                message="Selected adapter binding does not match the admitted capability.",
                details=mismatch_details,
            )
        )
        return

    checks.append(
        _readiness_item(
            code="adapter_visible",
            status="passed",
            message="Selected node adapter is tenant-visible and bound to the admitted capability.",
            details={"node_key": selected_node.get("node_key"), "adapter_id": str(adapter_id)},
        )
    )


def _quota_exceeded_response(exc: QuotaExceededError) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "QUOTA_EXCEEDED",
            "field": exc.field,
            "limit": exc.limit,
            "current": exc.current,
            "plan": exc.plan,
            "message": (
                f"You have reached the {exc.field} limit ({exc.limit}) for the {exc.plan!r} plan. Upgrade to continue."
            ),
        },
    )


def _mission_to_read(mission: Mission) -> MissionRead:
    return MissionRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        objective=mission.objective,
        status=mission.status,
        compliance_category=mission.compliance_category,
        jurisdiction=mission.jurisdiction,
        intake=mission.metadata_json.get(MISSION_INTAKE_METADATA_KEY, {}),
        created_at=mission.created_at.isoformat(),
        updated_at=mission.updated_at.isoformat(),
    )


def _mission_plan_to_read(mission: Mission) -> MissionPlanRead:
    return MissionPlanRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        plan=mission.metadata_json.get(MISSION_PLAN_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _mission_task_graph_to_read(mission: Mission) -> MissionTaskGraphRead:
    return MissionTaskGraphRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        task_graph=mission.metadata_json.get(MISSION_TASK_GRAPH_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _graph_materialization_to_read(mission: Mission) -> GraphMaterializationRead:
    return GraphMaterializationRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        materialization=mission.metadata_json.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY, {}),
        updated_at=mission.updated_at.isoformat(),
    )


def _mission_lifecycle_to_read(
    *,
    mission: Mission,
    evidence_records: list[Any],
    outcome_reviews: list[Any],
    retrieval_contracts: list[Any],
) -> MissionLifecycleRead:
    metadata = mission.metadata_json or {}
    intake = metadata.get(MISSION_INTAKE_METADATA_KEY)
    plan = metadata.get(MISSION_PLAN_METADATA_KEY)
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    runtime_admission = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    has_memory_promotions = False

    completeness = MissionLifecycleCompleteness(
        has_intake=isinstance(intake, dict),
        has_plan=isinstance(plan, dict),
        has_task_graph=isinstance(task_graph, dict),
        has_materialization=isinstance(materialization, dict),
        has_runtime_admission=(
            isinstance(runtime_admission, dict) and runtime_admission.get("admission_status") == "admitted"
        ),
        has_evidence=bool(evidence_records),
        has_outcome_review=bool(outcome_reviews),
        has_memory_promotions=has_memory_promotions,
        has_retrieval_contracts=bool(retrieval_contracts),
    )
    missing_next_steps: list[str] = []
    if not completeness.has_plan:
        missing_next_steps.append("create_mission_plan")
    if not completeness.has_task_graph:
        missing_next_steps.append("create_task_graph")
    if not completeness.has_materialization:
        missing_next_steps.append("materialize_task_graph")
    if not completeness.has_runtime_admission:
        missing_next_steps.append("admit_graph_to_runtime")
    if not completeness.has_evidence:
        missing_next_steps.append("attach_evidence")
    if not completeness.has_outcome_review:
        missing_next_steps.append("create_outcome_review")
    if not completeness.has_memory_promotions:
        missing_next_steps.append("review_memory_promotion")
    if not completeness.has_retrieval_contracts:
        missing_next_steps.append("create_retrieval_contract")

    return MissionLifecycleRead(
        mission=MissionLifecycleMissionSummary(
            mission_id=mission.id,
            tenant_id=mission.tenant_id,
            objective=mission.objective,
            status=mission.status,
            compliance_category=mission.compliance_category,
            jurisdiction=mission.jurisdiction,
            created_at=mission.created_at.isoformat(),
            updated_at=mission.updated_at.isoformat(),
        ),
        intake=intake if isinstance(intake, dict) else None,
        plan=plan if isinstance(plan, dict) else None,
        task_graph=task_graph if isinstance(task_graph, dict) else None,
        materialization=materialization if isinstance(materialization, dict) else None,
        runtime_admission=runtime_admission if isinstance(runtime_admission, dict) else None,
        evidence=MissionLifecycleEvidenceSummary(
            count=len(evidence_records),
            records=[
                MissionLifecycleEvidenceItem(
                    evidence_id=record.id,
                    evidence_type=record.evidence_type,
                    evidence_source=record.evidence_source,
                    collection_status=record.collection_status,
                    confidence=record.confidence,
                    created_at=record.created_at.isoformat(),
                    updated_at=record.updated_at.isoformat(),
                )
                for record in evidence_records
            ],
        ),
        outcome_reviews=MissionLifecycleOutcomeReviewSummary(
            count=len(outcome_reviews),
            records=[
                MissionLifecycleOutcomeReviewItem(
                    review_id=review.id,
                    review_status=review.review_status,
                    review_decision=review.review_decision,
                    reviewer_type=review.reviewer_type,
                    confidence=review.confidence,
                    created_at=review.created_at.isoformat(),
                    updated_at=review.updated_at.isoformat(),
                )
                for review in outcome_reviews
            ],
        ),
        memory_promotions=MissionLifecycleMemoryPromotionSummary(count=0, records=[]),
        retrieval_contracts=MissionLifecycleRetrievalContractSummary(
            count=len(retrieval_contracts),
            records=[
                MissionLifecycleRetrievalContractItem(
                    retrieval_id=retrieval.id,
                    retrieval_strategy=retrieval.retrieval_strategy,
                    retrieval_status=retrieval.retrieval_status,
                    confidence=retrieval.confidence,
                    created_at=retrieval.created_at.isoformat(),
                    updated_at=retrieval.updated_at.isoformat(),
                )
                for retrieval in retrieval_contracts
            ],
        ),
        completeness=completeness,
        missing_next_steps=missing_next_steps,
    )


@router.post("", response_model=MissionRead, status_code=201)
def create_mission(
    body: MissionCreate,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionRead:
    """Create a tenant-owned mission intake record without queueing runtime work."""
    try:
        QuotaEnforcementService(db).check_and_record_mission_creation(tenant_id)
    except QuotaExceededError as exc:
        raise _quota_exceeded_response(exc) from exc

    intake_metadata = build_mission_intake_metadata(
        success_criteria=[criterion.model_dump() for criterion in body.success_criteria],
        constraints=[constraint.model_dump() for constraint in body.constraints],
        operator_notes=body.operator_notes,
        context=body.context,
        priority=body.priority,
        approval_required=body.approval_required,
        approval_expectations=body.approval_expectations,
        budget_limits=body.budget_limits.model_dump(exclude_none=True) if body.budget_limits else None,
        scope_limits=body.scope_limits,
        allowed_actions=body.allowed_actions,
        allowed_tools=body.allowed_tools,
    )
    mission = MissionRepository(db).add(
        Mission(
            tenant_id=str(tenant_id),
            objective=body.objective,
            status=MissionState.PLANNED.value,
            compliance_category=body.compliance_category,
            jurisdiction=body.jurisdiction,
            metadata_json=intake_metadata,
        )
    )
    return _mission_to_read(mission)


@router.get("/{mission_id}", response_model=MissionRead)
def read_mission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionRead:
    """Read one tenant-owned mission through a tenant-scoped repository query."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    return _mission_to_read(mission)


@router.get("/{mission_id}/lifecycle", response_model=MissionLifecycleRead)
def read_mission_lifecycle(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionLifecycleRead:
    """Read one mission as a tenant-scoped product lifecycle without runtime side effects."""
    tenant_scope = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_scope)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    evidence_records = EvidenceRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    outcome_reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_scope)
    retrieval_contracts = RetrievalContractRepository(db).list_for_mission(
        mission_id=mission_id, tenant_id=tenant_scope
    )
    return _mission_lifecycle_to_read(
        mission=mission,
        evidence_records=evidence_records,
        outcome_reviews=outcome_reviews,
        retrieval_contracts=retrieval_contracts,
    )


@router.put("/{mission_id}/plan", response_model=MissionPlanRead)
def upsert_mission_plan(
    mission_id: UUID,
    body: MissionPlanWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionPlanRead:
    """Create or replace a tenant-scoped mission plan without queueing work."""
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    plan_metadata = build_mission_plan_metadata(
        planning_status=body.planning_status,
        phases=[phase.model_dump() for phase in body.phases],
        planning_notes=body.planning_notes,
        desired_outputs=[output.model_dump() for output in body.desired_outputs],
        capability_requirements=[requirement.model_dump() for requirement in body.capability_requirements],
        execution_strategy_hints=body.execution_strategy_hints,
        approval_gates=[gate.model_dump() for gate in body.approval_gates],
        operator_overrides=body.operator_overrides,
        estimated_scope=body.estimated_scope.model_dump(exclude_none=True),
        risk_annotations=[risk.model_dump() for risk in body.risk_annotations],
    )
    metadata = dict(mission.metadata_json or {})
    metadata.update(plan_metadata)
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _mission_plan_to_read(mission)


@router.get("/{mission_id}/plan", response_model=MissionPlanRead)
def read_mission_plan(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionPlanRead:
    """Read a tenant-scoped mission plan if one has been persisted."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_PLAN_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission plan not found")
    return _mission_plan_to_read(mission)


@router.put("/{mission_id}/task-graph", response_model=MissionTaskGraphRead)
def upsert_mission_task_graph(
    mission_id: UUID,
    body: MissionTaskGraphWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionTaskGraphRead:
    """Create or replace a tenant-scoped task graph contract without queueing work."""
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    graph_updated_at = datetime.now(UTC).isoformat()
    validation_metadata = {
        "validation_status": "valid",
        "validated_at": graph_updated_at,
        "node_count": len(body.nodes),
        "edge_count": len(body.edges),
        "cycle_check": "passed",
        "missing_node_check": "passed",
        "duplicate_node_key_check": "passed",
    }
    metadata = dict(mission.metadata_json or {})
    previous_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    graph_version = _next_task_graph_version(previous_graph)
    graph_nodes = [node.model_dump(mode="json", exclude_none=True) for node in body.nodes]
    graph_edges = [edge.model_dump(exclude_none=True) for edge in body.edges]
    graph_fingerprint = _task_graph_fingerprint(
        mission_id=str(mission_id),
        graph_status=body.graph_status,
        nodes=graph_nodes,
        edges=graph_edges,
        operator_notes=body.operator_notes,
    )
    graph_metadata = build_mission_task_graph_metadata(
        mission_id=str(mission_id),
        graph_status=body.graph_status,
        graph_version=graph_version,
        graph_fingerprint=graph_fingerprint,
        nodes=graph_nodes,
        edges=graph_edges,
        operator_notes=body.operator_notes,
        validation_metadata=validation_metadata,
    )
    metadata.update(graph_metadata)
    _supersede_graph_materialization(
        metadata=metadata,
        graph_version=graph_version,
        graph_fingerprint=graph_fingerprint,
        updated_at=graph_updated_at,
    )
    _supersede_runtime_admission(
        metadata=metadata,
        graph_version=graph_version,
        graph_fingerprint=graph_fingerprint,
        updated_at=graph_updated_at,
    )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=str(tenant_id),
            mission_id=mission_id,
        )
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="task_graph_replaced",
        updated_at=graph_updated_at,
        supersession={
            "superseded_by_graph_version": graph_version,
            "superseded_by_graph_fingerprint": graph_fingerprint,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _mission_task_graph_to_read(mission)


@router.get("/{mission_id}/task-graph", response_model=MissionTaskGraphRead)
def read_mission_task_graph(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> MissionTaskGraphRead:
    """Read a tenant-scoped task graph contract if one has been persisted."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_TASK_GRAPH_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission task graph not found")
    return _mission_task_graph_to_read(mission)


@router.post("/{mission_id}/materialize-graph", response_model=GraphMaterializationRead)
def materialize_mission_graph(
    mission_id: UUID,
    body: GraphMaterializationWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> GraphMaterializationRead:
    """Persist planner-to-graph materialization metadata without runtime work."""
    tenant_id_str = str(tenant_id)
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before materialization")

    graph_nodes = task_graph.get("nodes")
    if not isinstance(graph_nodes, list):
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before materialization")
    node_keys = {node.get("key") for node in graph_nodes if isinstance(node, dict)}
    if len(node_keys) != len(graph_nodes) or any(not isinstance(key, str) or not key for key in node_keys):
        raise HTTPException(status_code=400, detail="mission task graph nodes must have valid keys")

    capability_repo = CapabilityRepository(db)
    for selection in body.capability_selection_provenance:
        if selection.node_key not in node_keys:
            raise HTTPException(
                status_code=400, detail=f"capability selection references missing node: {selection.node_key}"
            )
        if selection.capability_id is not None:
            capability = capability_repo.get_visible_for_tenant(
                capability_id=selection.capability_id, tenant_id=tenant_id_str
            )
            if capability is None:
                raise HTTPException(
                    status_code=400, detail=f"capability not found for tenant: {selection.capability_id}"
                )

    previous = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    previous_version = previous.get("materialization_version", 0) if isinstance(previous, dict) else 0
    now = datetime.now(UTC).isoformat()
    materialization_metadata = build_graph_materialization_metadata(
        mission_id=str(mission_id),
        materialization_status=body.materialization_status,
        materialization_source=body.materialization_source,
        materialization_source_version=body.materialization_source_version,
        materialization_version=previous_version + 1,
        planner_provenance=body.planner_provenance.model_dump(mode="json", exclude_none=True),
        capability_selection_provenance=[
            selection.model_dump(mode="json", exclude_none=True) for selection in body.capability_selection_provenance
        ],
        graph_validation_result=body.graph_validation_result.model_dump(mode="json", exclude_none=True),
        operator_review=body.operator_review.model_dump(mode="json", exclude_none=True),
        graph_generation_metadata=body.graph_generation_metadata.model_dump(mode="json", exclude_none=True),
        deterministic_compilation_metadata=body.deterministic_compilation_metadata.model_dump(
            mode="json", exclude_none=True
        ),
        generation_notes=body.generation_notes,
        materialized_at=previous.get("materialized_at", now) if isinstance(previous, dict) else now,
        updated_at=now,
        graph_reference={
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": task_graph.get("schema_version"),
            "graph_status": task_graph.get("graph_status"),
            "graph_version": task_graph.get("graph_version"),
            "graph_fingerprint": task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph),
            "node_count": len(graph_nodes),
            "edge_count": len(task_graph.get("edges", [])) if isinstance(task_graph.get("edges", []), list) else 0,
        },
    )
    if isinstance(metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY), dict):
        _supersede_runtime_admission_for_materialization(
            metadata=metadata,
            materialization_version=previous_version + 1,
            updated_at=now,
        )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=tenant_id_str,
            mission_id=mission_id,
        )
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="graph_materialization_replaced",
        updated_at=now,
        supersession={
            "superseded_by_materialization_version": previous_version + 1,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    metadata.update(materialization_metadata)
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _graph_materialization_to_read(mission)


@router.get("/{mission_id}/materialization", response_model=GraphMaterializationRead)
def read_mission_graph_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> GraphMaterializationRead:
    """Read tenant-scoped planner-to-graph materialization metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_GRAPH_MATERIALIZATION_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission graph materialization not found")
    return _graph_materialization_to_read(mission)


@router.post("/{mission_id}/runtime-admission", response_model=RuntimeAdmissionRead)
def admit_mission_graph_to_runtime(
    mission_id: UUID,
    body: RuntimeAdmissionWrite,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeAdmissionRead:
    """Persist graph-to-runtime admission metadata without queueing or dispatch."""
    tenant_id_str = str(tenant_id)
    repo = MissionRepository(db)
    mission = repo.get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    task_graph = metadata.get(MISSION_TASK_GRAPH_METADATA_KEY)
    if not isinstance(task_graph, dict):
        raise HTTPException(status_code=400, detail="mission task graph is required before runtime admission")

    materialization = metadata.get(MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        raise HTTPException(
            status_code=400, detail="mission graph materialization is required before runtime admission"
        )

    if materialization.get("materialization_status") == "superseded":
        raise HTTPException(status_code=400, detail="superseded graph materialization cannot be admitted")

    graph_nodes = task_graph.get("nodes")
    if not isinstance(graph_nodes, list) or not all(isinstance(node, dict) for node in graph_nodes):
        raise HTTPException(status_code=400, detail="mission task graph nodes are required before runtime admission")
    nodes_by_key = {node.get("key"): node for node in graph_nodes if isinstance(node.get("key"), str)}
    if len(nodes_by_key) != len(graph_nodes):
        raise HTTPException(status_code=400, detail="mission task graph nodes must have valid keys")

    graph_version = task_graph.get("graph_version")
    graph_fingerprint = task_graph.get("graph_fingerprint") or _fingerprint_existing_task_graph(task_graph)
    graph_reference = materialization.get("graph_reference")
    if not isinstance(graph_reference, dict):
        raise HTTPException(
            status_code=400, detail="materialization graph reference is required before runtime admission"
        )
    if (
        graph_reference.get("graph_version") != graph_version
        or graph_reference.get("graph_fingerprint") != graph_fingerprint
    ):
        raise HTTPException(status_code=400, detail="materialization graph reference does not match current task graph")

    outcome_reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_id_str)
    rejected_reviews = [
        review
        for review in outcome_reviews
        if review.review_status == "rejected" or review.review_decision == "rejected"
    ]
    if rejected_reviews:
        raise HTTPException(status_code=400, detail="rejected outcome review blocks runtime admission")

    capability_repo = CapabilityRepository(db)
    adapter_repo = CapabilityAdapterRepository(db)
    selections_by_node = {
        selection.get("node_key"): selection
        for selection in materialization.get("capability_selection_provenance", [])
        if isinstance(selection, dict) and isinstance(selection.get("node_key"), str)
    }

    validation_checks: list[dict[str, str]] = []
    selected_nodes: list[dict[str, Any]] = []
    for selection in body.selected_nodes:
        node = nodes_by_key.get(selection.node_key)
        if node is None:
            raise HTTPException(
                status_code=400, detail=f"runtime admission references missing node: {selection.node_key}"
            )

        runtime_task_type = selection.runtime_task_type or node.get("intended_task_type")
        if not isinstance(runtime_task_type, str) or not runtime_task_type.strip():
            raise HTTPException(
                status_code=400, detail=f"runtime admission node lacks runtime task type: {selection.node_key}"
            )
        runtime_task_type = runtime_task_type.strip()

        node_capability_refs = (
            node.get("capability_references") if isinstance(node.get("capability_references"), list) else []
        )
        materialized_selection = selections_by_node.get(selection.node_key)
        capability_id = selection.capability_id
        materialized_capability_id: UUID | None = None
        if isinstance(materialized_selection, dict):
            raw_materialized_capability_id = materialized_selection.get("capability_id")
            if isinstance(raw_materialized_capability_id, str):
                try:
                    materialized_capability_id = UUID(raw_materialized_capability_id)
                except ValueError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"materialization capability_id is invalid for node: {selection.node_key}",
                    ) from exc

        if (
            capability_id is not None
            and materialized_capability_id is not None
            and capability_id != materialized_capability_id
        ):
            raise HTTPException(
                status_code=400,
                detail=f"runtime admission capability conflicts with materialization: {selection.node_key}",
            )

        if capability_id is None and materialized_capability_id is not None:
            capability_id = materialized_capability_id

        if capability_id is None:
            for capability_ref in node_capability_refs:
                if isinstance(capability_ref, dict) and isinstance(capability_ref.get("capability_id"), str):
                    try:
                        capability_id = UUID(capability_ref["capability_id"])
                    except ValueError as exc:
                        raise HTTPException(
                            status_code=400,
                            detail=f"task graph capability_id is invalid for node: {selection.node_key}",
                        ) from exc
                    break

        if capability_id is None and not node_capability_refs:
            raise HTTPException(
                status_code=400, detail=f"runtime admission node lacks capability reference: {selection.node_key}"
            )
        if capability_id is not None:
            capability = capability_repo.get_visible_for_tenant(capability_id=capability_id, tenant_id=tenant_id_str)
            if capability is None:
                raise HTTPException(status_code=400, detail=f"capability not found for tenant: {capability_id}")
        else:
            visible_capability_found = False
            for capability_ref in node_capability_refs:
                if not isinstance(capability_ref, dict):
                    continue
                capability_name = capability_ref.get("name")
                capability_version = capability_ref.get("version")
                if not isinstance(capability_name, str) or not capability_name.strip():
                    continue
                if not isinstance(capability_version, str) or not capability_version.strip():
                    continue

                capability = capability_repo.get_conflict_for_scope(
                    name=capability_name.strip(),
                    version=capability_version.strip(),
                    tenant_id=tenant_id_str,
                )
                if capability is None:
                    capability = capability_repo.get_conflict_for_scope(
                        name=capability_name.strip(),
                        version=capability_version.strip(),
                        tenant_id=None,
                    )
                if capability is not None:
                    visible_capability_found = True
                    break

            if not visible_capability_found:
                raise HTTPException(
                    status_code=400,
                    detail=f"runtime admission node lacks visible capability reference: {selection.node_key}",
                )

        adapter_id = selection.adapter_id
        if adapter_id is not None:
            adapter = adapter_repo.get_visible_for_tenant(adapter_id=adapter_id, tenant_id=tenant_id_str)
            if adapter is None:
                raise HTTPException(status_code=400, detail=f"capability adapter not found for tenant: {adapter_id}")

        validation_checks.append({"name": f"node:{selection.node_key}", "status": "passed"})
        selected_nodes.append(
            {
                "node_key": selection.node_key,
                "runtime_task_type": runtime_task_type,
                "capability_id": str(capability_id) if capability_id is not None else None,
                "adapter_id": str(adapter_id) if adapter_id is not None else None,
                "graph_node_reference": {
                    "key": node.get("key"),
                    "name": node.get("name"),
                    "intended_task_type": node.get("intended_task_type"),
                },
                "materialization_selection_reference": materialized_selection,
                "operator_notes": selection.operator_notes,
            }
        )

    previous = metadata.get(MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    previous_version = previous.get("admission_version", 0) if isinstance(previous, dict) else 0
    now = datetime.now(UTC).isoformat()
    runtime_admission_metadata = build_runtime_admission_metadata(
        mission_id=str(mission_id),
        admission_status=body.admission_status,
        admission_version=previous_version + 1,
        admitted_by=body.admitted_by,
        admitted_at=(
            previous.get("admitted_at", now)
            if isinstance(previous, dict) and previous.get("admission_status") != "superseded"
            else now
        ),
        updated_at=now,
        graph_reference={
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": task_graph.get("schema_version"),
            "graph_status": task_graph.get("graph_status"),
            "graph_version": graph_version,
            "graph_fingerprint": graph_fingerprint,
            "node_count": len(graph_nodes),
        },
        materialization_reference={
            "metadata_key": MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
            "schema_version": materialization.get("schema_version"),
            "materialization_status": materialization.get("materialization_status"),
            "materialization_version": materialization.get("materialization_version"),
            "graph_reference": graph_reference,
        },
        selected_nodes=selected_nodes,
        validation_result={
            "validation_status": "valid",
            "summary": "Runtime admission metadata validated; no runtime work was queued or dispatched.",
            "validated_at": now,
            "checks": validation_checks,
            "gaps": body.validation_notes,
        },
        execution_task_records=[],
        runtime_authority={
            "creates_execution_tasks": False,
            "enqueues_work": False,
            "dispatches_workers": False,
            "requires_explicit_queue_admission_for_execution": True,
        },
    )
    cancelled_task_ids: list[str] = []
    if isinstance(metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY), dict):
        cancelled_task_ids = _cancel_superseded_materialized_planned_tasks(
            metadata=metadata,
            task_repo=ExecutionTaskRepository(db),
            tenant_id=tenant_id_str,
            mission_id=mission_id,
        )
    metadata.update(runtime_admission_metadata)
    supersede_runtime_task_materialization(
        metadata=metadata,
        reason="runtime_admission_replaced",
        updated_at=now,
        supersession={
            "superseded_by_admission_version": previous_version + 1,
            "cancelled_execution_task_ids": cancelled_task_ids,
        },
    )
    mission = repo.update_metadata(mission=mission, metadata_json=metadata)
    return _runtime_admission_to_read(mission)


def _build_mission_runtime_readiness(
    *,
    mission_id: UUID,
    tenant_id: _uuid.UUID,
    db: Session,
) -> RuntimeReadinessRead:
    """Build the shared read-only runtime admission readiness result."""
    tenant_id_str = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = mission.metadata_json or {}
    task_graph = _runtime_readiness_reference(metadata, MISSION_TASK_GRAPH_METADATA_KEY)
    materialization = _runtime_readiness_reference(metadata, MISSION_GRAPH_MATERIALIZATION_METADATA_KEY)
    admission = _runtime_readiness_reference(metadata, MISSION_RUNTIME_ADMISSION_METADATA_KEY)
    checked_at = datetime.now(UTC).isoformat()
    checks: list[RuntimeReadinessItem] = []
    blockers: list[RuntimeReadinessItem] = []
    warnings: list[RuntimeReadinessItem] = []
    incomplete_codes: set[str] = set()

    if task_graph is None:
        blockers.append(
            _readiness_item(
                code="missing_task_graph",
                status="failed",
                message="Current task graph metadata is required before runtime readiness can pass.",
            )
        )
        incomplete_codes.add("missing_task_graph")
    else:
        checks.append(
            _readiness_item(
                code="task_graph_present",
                status="passed",
                message="Current task graph metadata is present.",
                details={
                    "graph_version": task_graph.get("graph_version"),
                    "graph_fingerprint": task_graph.get("graph_fingerprint"),
                },
            )
        )

    if materialization is None:
        blockers.append(
            _readiness_item(
                code="missing_materialization",
                status="failed",
                message="Current graph materialization metadata is required before runtime readiness can pass.",
            )
        )
        incomplete_codes.add("missing_materialization")
    elif materialization.get("materialization_status") == "superseded":
        blockers.append(
            _readiness_item(
                code="materialization_superseded",
                status="failed",
                message="Current graph materialization is superseded.",
                details={"materialization_version": materialization.get("materialization_version")},
            )
        )
    else:
        checks.append(
            _readiness_item(
                code="materialization_current",
                status="passed",
                message="Current graph materialization is present and not superseded.",
                details={
                    "materialization_status": materialization.get("materialization_status"),
                    "materialization_version": materialization.get("materialization_version"),
                },
            )
        )

    if admission is None:
        blockers.append(
            _readiness_item(
                code="missing_runtime_admission",
                status="failed",
                message="Runtime admission metadata is required before runtime readiness can pass.",
            )
        )
        incomplete_codes.add("missing_runtime_admission")
    elif admission.get("admission_status") == "superseded":
        blockers.append(
            _readiness_item(
                code="admission_superseded",
                status="failed",
                message="Runtime admission metadata is superseded.",
                details={"admission_version": admission.get("admission_version")},
            )
        )
    elif admission.get("admission_status") != "admitted":
        blockers.append(
            _readiness_item(
                code="runtime_admission_not_admitted",
                status="failed",
                message="Runtime admission must have admission_status='admitted' before readiness can pass.",
                details={"admission_status": admission.get("admission_status")},
            )
        )
    else:
        checks.append(
            _readiness_item(
                code="runtime_admission_admitted",
                status="passed",
                message="Runtime admission is admitted.",
                details={"admission_version": admission.get("admission_version")},
            )
        )

    selected_nodes = admission.get("selected_nodes") if isinstance(admission, dict) else []
    if not isinstance(selected_nodes, list):
        selected_nodes = []
    if isinstance(admission, dict) and not selected_nodes:
        blockers.append(
            _readiness_item(
                code="validation_gap",
                status="failed",
                message="Runtime admission contains no selected nodes for readiness validation.",
            )
        )
        incomplete_codes.add("validation_gap")

    if task_graph is not None and admission is not None:
        if _graph_matches_reference(task_graph=task_graph, graph_reference=admission.get("graph_reference")):
            checks.append(
                _readiness_item(
                    code="graph_reference_current",
                    status="passed",
                    message="Admission graph reference matches the current task graph.",
                )
            )
        else:
            blockers.append(
                _readiness_item(
                    code="graph_reference_mismatch",
                    status="failed",
                    message="Admission graph reference does not match the current task graph version/fingerprint.",
                    details={
                        "current_graph_version": task_graph.get("graph_version"),
                        "current_graph_fingerprint": task_graph.get("graph_fingerprint"),
                        "admission_graph_reference": admission.get("graph_reference"),
                    },
                )
            )

    if materialization is not None and admission is not None:
        if _materialization_matches_reference(
            materialization=materialization, materialization_reference=admission.get("materialization_reference")
        ):
            checks.append(
                _readiness_item(
                    code="materialization_reference_current",
                    status="passed",
                    message="Admission materialization reference matches the current materialization.",
                )
            )
        else:
            blockers.append(
                _readiness_item(
                    code="materialization_reference_mismatch",
                    status="failed",
                    message="Admission materialization reference does not match the current materialization.",
                    details={
                        "current_materialization_version": materialization.get("materialization_version"),
                        "admission_materialization_reference": admission.get("materialization_reference"),
                    },
                )
            )

    outcome_reviews = OutcomeReviewRepository(db).list_for_mission(mission_id=mission_id, tenant_id=tenant_id_str)
    rejected_reviews = [
        review
        for review in outcome_reviews
        if getattr(review, "review_status", None) == "rejected"
        or getattr(review, "review_decision", None) == "rejected"
    ]
    if rejected_reviews:
        blockers.append(
            _readiness_item(
                code="rejected_outcome_review",
                status="failed",
                message="At least one approved rejected outcome review blocks runtime materialization readiness.",
                details={"rejected_review_count": len(rejected_reviews)},
            )
        )
    else:
        checks.append(
            _readiness_item(
                code="outcome_reviews_non_blocking",
                status="passed",
                message="No approved rejected outcome review blocks runtime materialization readiness.",
                details={"review_count": len(outcome_reviews)},
            )
        )

    capability_repo = CapabilityRepository(db)
    adapter_repo = CapabilityAdapterRepository(db)
    nodes_by_key: dict[str, dict[str, Any]] = {}
    if task_graph is not None and isinstance(task_graph.get("nodes"), list):
        nodes_by_key = {node["key"]: node for node in task_graph["nodes"] if isinstance(node, dict) and node.get("key")}

    for selected_node in selected_nodes:
        if not isinstance(selected_node, dict):
            blockers.append(
                _readiness_item(
                    code="validation_gap",
                    status="failed",
                    message="Runtime admission selected node entry is malformed.",
                )
            )
            incomplete_codes.add("validation_gap")
            continue
        node_key = selected_node.get("node_key")
        node = nodes_by_key.get(node_key) if isinstance(node_key, str) else None
        if node is None:
            blockers.append(
                _readiness_item(
                    code="missing_selected_node",
                    status="failed",
                    message="Runtime admission selected node is missing from the current task graph.",
                    details={"node_key": node_key},
                )
            )
            continue

        checks.append(
            _readiness_item(
                code="selected_node_present",
                status="passed",
                message="Runtime admission selected node is present in the current task graph.",
                details={"node_key": node_key},
            )
        )
        runtime_task_type = selected_node.get("runtime_task_type") or node.get("intended_task_type")
        if not isinstance(runtime_task_type, str) or not runtime_task_type.strip():
            blockers.append(
                _readiness_item(
                    code="missing_runtime_task_type",
                    status="failed",
                    message="Runtime admission selected node lacks a runtime task type.",
                    details={"node_key": node_key},
                )
            )
            continue
        checks.append(
            _readiness_item(
                code="runtime_task_type_present",
                status="passed",
                message="Runtime admission selected node has a runtime task type.",
                details={"node_key": node_key, "runtime_task_type": runtime_task_type.strip()},
            )
        )

        capability_id, capability_name, capability_version = _resolve_capability_for_readiness(
            selected_node=selected_node,
            graph_node=node,
            capability_repo=capability_repo,
            tenant_id=tenant_id_str,
            blockers=blockers,
            checks=checks,
        )
        _validate_adapter_for_readiness(
            selected_node=selected_node,
            admitted_capability_id=capability_id,
            admitted_capability_name=capability_name,
            admitted_capability_version=capability_version,
            adapter_repo=adapter_repo,
            tenant_id=tenant_id_str,
            blockers=blockers,
            checks=checks,
        )

    validation_result = admission.get("validation_result") if isinstance(admission, dict) else None
    validation_gaps = validation_result.get("gaps") if isinstance(validation_result, dict) else None
    if validation_gaps:
        warning = _readiness_item(
            code="validation_gap",
            status="warning",
            message="Runtime admission includes validation notes that should be reviewed before task materialization.",
            details={"gaps": validation_gaps},
        )
        warnings.append(warning)
        checks.append(warning)

    ready = not blockers
    readiness_status: RuntimeReadinessStatus = "ready" if ready else "blocked"
    if not ready and any(blocker.code in incomplete_codes for blocker in blockers):
        readiness_status = "incomplete"

    return RuntimeReadinessRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        ready=ready,
        readiness_status=readiness_status,
        checked_at=checked_at,
        graph_reference=task_graph,
        materialization_reference=materialization,
        admission_reference=admission,
        selected_node_count=len(selected_nodes),
        checks=checks,
        blockers=blockers,
        warnings=warnings,
    )


@router.get("/{mission_id}/runtime-readiness", response_model=RuntimeReadinessRead)
def read_mission_runtime_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeReadinessRead:
    """Validate read-only runtime admission readiness without runtime authority."""
    return _build_mission_runtime_readiness(mission_id=mission_id, tenant_id=tenant_id, db=db)


def _runtime_preview_authority_flags() -> dict[str, bool]:
    return runtime_preview_authority_flags()


def _build_runtime_task_preview_items(
    *, mission_id: UUID, readiness: RuntimeReadinessRead
) -> list[RuntimeTaskPreviewItem]:
    return [
        RuntimeTaskPreviewItem.model_validate(item)
        for item in project_runtime_task_preview_items(mission_id=mission_id, readiness=readiness)
    ]


@router.get("/{mission_id}/runtime-task-preview", response_model=RuntimeTaskPreviewRead)
def read_mission_runtime_task_preview(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskPreviewRead:
    """Preview future ExecutionTask materialization without creating or queueing work."""
    readiness = _build_mission_runtime_readiness(mission_id=mission_id, tenant_id=tenant_id, db=db)
    tasks = _build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness) if readiness.ready else []
    preview_status: RuntimeTaskPreviewStatus = readiness.readiness_status
    if readiness.ready and len(tasks) != readiness.selected_node_count:
        preview_status = "incomplete"
    readiness_summary = {
        "readiness_status": readiness.readiness_status,
        "selected_node_count": readiness.selected_node_count,
        "check_count": len(readiness.checks),
        "blocker_count": len(readiness.blockers),
        "warning_count": len(readiness.warnings),
    }
    return RuntimeTaskPreviewRead(
        mission_id=readiness.mission_id,
        tenant_id=readiness.tenant_id,
        ready=readiness.ready and preview_status == "ready",
        preview_status=preview_status,
        checked_at=readiness.checked_at,
        readiness_summary=readiness_summary,
        task_count=len(tasks),
        tasks=tasks,
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        runtime_authority=_runtime_preview_authority_flags(),
    )


def _runtime_task_materialization_to_read(
    *,
    mission: Mission,
    metadata: dict[str, Any],
    blockers: list[RuntimeReadinessItem] | None = None,
    warnings: list[RuntimeReadinessItem] | None = None,
) -> RuntimeTaskMaterializationRead:
    raw_task_ids = metadata.get("created_execution_task_ids")
    created_task_ids = [UUID(str(task_id)) for task_id in raw_task_ids] if isinstance(raw_task_ids, list) else []
    raw_status = metadata.get("materialization_status")
    materialization_status: RuntimeTaskMaterializationStatus = (
        raw_status if raw_status in {"materialized", "blocked", "superseded"} else "blocked"
    )
    raw_authority = metadata.get("runtime_authority")
    runtime_authority: dict[str, bool] = (
        {str(key): bool(value) for key, value in raw_authority.items()}
        if isinstance(raw_authority, dict)
        else runtime_materialization_authority_flags()
    )
    return RuntimeTaskMaterializationRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        materialization_status=materialization_status,
        materialization_version=(
            metadata.get("materialization_version")
            if isinstance(metadata.get("materialization_version"), int)
            else None
        ),
        created_execution_task_ids=created_task_ids,
        task_count=metadata.get("task_count", len(created_task_ids))
        if isinstance(metadata.get("task_count"), int)
        else len(created_task_ids),
        graph_reference=metadata.get("graph_reference") if isinstance(metadata.get("graph_reference"), dict) else None,
        materialization_reference=(
            metadata.get("materialization_reference")
            if isinstance(metadata.get("materialization_reference"), dict)
            else None
        ),
        admission_reference=metadata.get("admission_reference")
        if isinstance(metadata.get("admission_reference"), dict)
        else None,
        runtime_authority=runtime_authority,
        blockers=blockers or [],
        warnings=warnings or [],
        updated_at=str(metadata.get("updated_at") or mission.updated_at.isoformat()),
    )


def _build_blocked_runtime_task_materialization_read(
    *, readiness: RuntimeReadinessRead, status: RuntimeTaskMaterializationStatus = "blocked"
) -> RuntimeTaskMaterializationRead:
    return RuntimeTaskMaterializationRead(
        mission_id=readiness.mission_id,
        tenant_id=readiness.tenant_id,
        materialization_status=status,
        materialization_version=None,
        created_execution_task_ids=[],
        task_count=0,
        graph_reference=readiness.graph_reference,
        materialization_reference=readiness.materialization_reference,
        admission_reference=readiness.admission_reference,
        runtime_authority=runtime_materialization_authority_flags(),
        blockers=readiness.blockers,
        warnings=readiness.warnings,
        updated_at=readiness.checked_at,
    )


@router.get("/{mission_id}/runtime-task-materialization", response_model=RuntimeTaskMaterializationRead)
def read_mission_runtime_task_materialization(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskMaterializationRead:
    """Read tenant-scoped ExecutionTask materialization metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    materialization = (mission.metadata_json or {}).get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if not isinstance(materialization, dict):
        raise HTTPException(status_code=404, detail="mission runtime task materialization not found")
    return _runtime_task_materialization_to_read(mission=mission, metadata=materialization)


@router.post("/{mission_id}/runtime-task-materialization", response_model=RuntimeTaskMaterializationRead)
def materialize_mission_runtime_tasks(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeTaskMaterializationRead:
    """Create planned ExecutionTask rows from a ready admitted mission graph without queueing work."""
    tenant_id_str = str(tenant_id)
    mission_repo = MissionRepository(db)
    mission = mission_repo.lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    readiness = _build_mission_runtime_readiness(mission_id=mission_id, tenant_id=tenant_id, db=db)
    if not readiness.ready:
        if any(blocker.code == "runtime_admission_not_admitted" for blocker in readiness.blockers):
            raise HTTPException(status_code=400, detail="runtime admission must be admitted before materialization")
        if any(blocker.code == "graph_reference_mismatch" for blocker in readiness.blockers):
            raise HTTPException(
                status_code=400, detail="runtime admission graph reference does not match current task graph"
            )
        return _build_blocked_runtime_task_materialization_read(readiness=readiness)

    tasks = _build_runtime_task_preview_items(mission_id=mission_id, readiness=readiness)
    if len(tasks) != readiness.selected_node_count:
        incomplete_readiness_payload = readiness.model_dump()
        incomplete_readiness_payload["ready"] = False
        incomplete_readiness_payload["readiness_status"] = "incomplete"
        incomplete_readiness_payload["blockers"] = [
            *readiness.blockers,
            _readiness_item(
                code="runtime_task_preview_incomplete",
                status="failed",
                message="Runtime task preview did not produce one task for each selected node.",
                details={"task_count": len(tasks), "selected_node_count": readiness.selected_node_count},
            ),
        ]
        return _build_blocked_runtime_task_materialization_read(
            readiness=RuntimeReadinessRead.model_validate(incomplete_readiness_payload)
        )

    metadata = dict(mission.metadata_json or {})
    existing = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    if isinstance(existing, dict) and materialization_reference_current(
        task_materialization=existing,
        graph_reference=readiness.graph_reference,
        materialization_reference=readiness.materialization_reference,
        admission_reference=readiness.admission_reference,
    ):
        return _runtime_task_materialization_to_read(
            mission=mission, metadata=existing, blockers=readiness.blockers, warnings=readiness.warnings
        )

    previous_version = existing.get("materialization_version", 0) if isinstance(existing, dict) else 0
    task_repo = ExecutionTaskRepository(db)
    created_task_ids: list[str] = []
    for task_preview in tasks:
        payload = build_execution_task_payload(task_preview)
        task = ExecutionTask(
            tenant_id=tenant_id_str,
            mission_id=mission_id,
            title=task_preview.graph_node_name or task_preview.graph_node_key,
            description=(
                task_preview.operator_notes
                or f"Planned runtime task for mission graph node {task_preview.graph_node_key}."
            ),
            status=ExecutionTaskState.PLANNED.value,
            metadata_json=payload,
            compliance_category=mission.compliance_category,
            jurisdiction=mission.jurisdiction,
        )
        created = task_repo.add(task)
        created_task_ids.append(str(created.id))

    now = datetime.now(UTC).isoformat()
    task_materialization = build_runtime_task_materialization_metadata(
        mission_id=mission_id,
        materialization_version=previous_version + 1,
        created_execution_task_ids=created_task_ids,
        graph_reference=readiness.graph_reference,
        materialization_reference=readiness.materialization_reference,
        admission_reference=readiness.admission_reference,
        materialized_by="runtime-task-materialization-api",
        now=now,
    )
    metadata[MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY] = task_materialization
    mission = mission_repo.update_metadata(mission=mission, metadata_json=metadata)
    return _runtime_task_materialization_to_read(
        mission=mission, metadata=task_materialization, blockers=readiness.blockers, warnings=readiness.warnings
    )


def _runtime_queue_admission_blocker(
    *, task_id: UUID | None, code: str, message: str, state: str | None = None, reason: str | None = None
) -> dict[str, Any]:
    blocker: dict[str, Any] = {"code": code, "message": message}
    if task_id is not None:
        blocker["task_id"] = str(task_id)
    if state is not None:
        blocker["state"] = state
    if reason is not None:
        blocker["reason"] = reason
    return blocker


def _runtime_queue_admission_status(*, admitted_task_ids: list[str], blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "admitted"
    if admitted_task_ids:
        return "partially_admitted"
    return "blocked"


def _build_runtime_queue_admission_metadata(
    *,
    mission_id: UUID,
    tenant_id: str,
    materialized_task_ids: list[UUID],
    planned_task_ids: list[str],
    queued_task_ids: list[str],
    already_queued_task_ids: list[str],
    pending_review_task_ids: list[str],
    denied_tasks: list[dict[str, str | None]],
    blockers: list[dict[str, Any]],
    now: str,
) -> dict[str, Any]:
    admitted_task_ids = [*already_queued_task_ids, *queued_task_ids]
    blocked_task_ids = [str(blocker["task_id"]) for blocker in blockers if isinstance(blocker.get("task_id"), str)]
    admission_status = _runtime_queue_admission_status(admitted_task_ids=admitted_task_ids, blockers=blockers)
    return {
        "schema_version": MISSION_RUNTIME_QUEUE_ADMISSION_SCHEMA_VERSION,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": admission_status,
        "materialized_execution_task_ids": [str(task_id) for task_id in materialized_task_ids],
        "planned_execution_task_ids": planned_task_ids,
        "queued_execution_task_ids": queued_task_ids,
        "already_queued_execution_task_ids": already_queued_task_ids,
        "admitted_execution_task_ids": admitted_task_ids,
        "pending_review_execution_task_ids": pending_review_task_ids,
        "blocked_execution_task_ids": blocked_task_ids,
        "denied_tasks": denied_tasks,
        "blockers": blockers,
        "runtime_authority": {
            "creates_execution_tasks": False,
            "enqueues_work": True,
            "dispatches_workers": False,
            "executes_adapters": False,
            "calls_task_dispatcher": False,
            "calls_coordinator": True,
        },
        "updated_at": now,
    }


def _runtime_queue_admission_response(metadata: dict[str, Any]) -> dict[str, object]:
    return {
        "queued_task_ids": metadata.get("queued_execution_task_ids", []),
        "pending_review_task_ids": metadata.get("pending_review_execution_task_ids", []),
        "denied_tasks": metadata.get("denied_tasks", []),
        "admission_status": metadata.get("admission_status", "blocked"),
        "admitted_task_ids": metadata.get("admitted_execution_task_ids", []),
        "blocked_task_ids": metadata.get("blocked_execution_task_ids", []),
        "blockers": metadata.get("blockers", []),
        "runtime_queue_admission": metadata,
    }


def _runtime_dispatch_authority_flags() -> RuntimeDispatchAuthority:
    return RuntimeDispatchAuthority(
        creates_execution_tasks=False,
        enqueues_work=False,
        dispatches_workers=False,
        calls_executor=False,
        calls_coordinator=False,
        executes_adapters=False,
        read_only=True,
    )


def _runtime_dispatch_item(
    *, task_id: UUID | None, code: str, message: str, state: str | None = None, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    item: dict[str, Any] = {"code": code, "message": message}
    if task_id is not None:
        item["task_id"] = str(task_id)
    if state is not None:
        item["state"] = state
    if details:
        item["details"] = details
    return item


def _queue_admission_status(metadata: dict[str, Any]) -> str | None:
    raw_status = metadata.get("admission_status") or metadata.get("queue_admission_status")
    return raw_status if isinstance(raw_status, str) else None


def _uuid_set_from_metadata_list(metadata: dict[str, Any], key: str) -> set[UUID]:
    values = metadata.get(key)
    if not isinstance(values, list):
        return set()
    parsed: set[UUID] = set()
    for value in values:
        try:
            parsed.add(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return parsed


def _task_has_dispatch_task_type(task: ExecutionTask) -> bool:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    task_type = metadata.get("task_type")
    return isinstance(task_type, str) and bool(task_type.strip())


def _runtime_dispatch_readiness_status(
    *,
    dispatch_ready_task_ids: list[str],
    not_ready_task_ids: list[str],
    blocked_task_ids: list[str],
    skipped_task_ids: list[str],
) -> RuntimeDispatchReadinessStatus:
    if blocked_task_ids or not dispatch_ready_task_ids:
        if dispatch_ready_task_ids:
            return "partial"
        return "blocked"
    if not_ready_task_ids or skipped_task_ids:
        return "partial"
    return "ready"


def _build_runtime_dispatch_readiness(
    *, mission_id: UUID, tenant_id: _uuid.UUID, db: Session
) -> RuntimeDispatchReadinessRead:
    """Build the read-only dispatch readiness contract for a tenant mission."""
    tenant_id_str = str(tenant_id)
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    checked_at = datetime.now(UTC).isoformat()
    metadata = mission.metadata_json if isinstance(mission.metadata_json, dict) else {}
    materialization = metadata.get(MISSION_RUNTIME_TASK_MATERIALIZATION_METADATA_KEY)
    queue_admission = metadata.get(MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    materialized_task_ids: list[UUID] = []
    if not isinstance(materialization, dict):
        blockers.append(
            _runtime_dispatch_item(
                task_id=None,
                code="runtime_task_materialization_missing",
                message="Mission has no runtime task materialization metadata.",
            )
        )
        materialization_reference: dict[str, Any] | None = None
    else:
        materialization_reference = materialization
        materialized_task_ids = _current_materialized_execution_task_ids(metadata)
        if not materialized_task_ids:
            blockers.append(
                _runtime_dispatch_item(
                    task_id=None,
                    code="no_current_materialized_tasks",
                    message="Current runtime task materialization has no dispatchable execution task IDs.",
                )
            )

    queue_admitted_task_ids: set[UUID] = set()
    if not isinstance(queue_admission, dict):
        blockers.append(
            _runtime_dispatch_item(
                task_id=None,
                code="runtime_queue_admission_missing",
                message="Mission has no runtime queue admission metadata.",
            )
        )
        queue_admission_reference: dict[str, Any] | None = None
    else:
        queue_admission_reference = queue_admission
        admission_status = _queue_admission_status(queue_admission)
        if admission_status not in {"admitted", "partially_admitted"}:
            blockers.append(
                _runtime_dispatch_item(
                    task_id=None,
                    code="runtime_queue_admission_not_admitted",
                    message="Runtime queue admission status is not admitted or partially admitted.",
                    details={"admission_status": admission_status},
                )
            )
        if queue_admission.get("tenant_id") not in {tenant_id_str, None}:
            blockers.append(
                _runtime_dispatch_item(
                    task_id=None,
                    code="runtime_queue_admission_tenant_mismatch",
                    message="Runtime queue admission metadata belongs to a different tenant.",
                )
            )
        if queue_admission.get("mission_id") not in {str(mission_id), None}:
            blockers.append(
                _runtime_dispatch_item(
                    task_id=None,
                    code="runtime_queue_admission_mission_mismatch",
                    message="Runtime queue admission metadata belongs to a different mission.",
                )
            )

        queue_materialized_task_ids = _uuid_set_from_metadata_list(queue_admission, "materialized_execution_task_ids")
        current_materialized_task_ids = set(materialized_task_ids)
        if current_materialized_task_ids and queue_materialized_task_ids != current_materialized_task_ids:
            blockers.append(
                _runtime_dispatch_item(
                    task_id=None,
                    code="queue_admission_materialization_mismatch",
                    message="Runtime queue admission does not cover the current runtime task materialization.",
                    details={
                        "current_materialized_task_ids": sorted(
                            str(task_id) for task_id in current_materialized_task_ids
                        ),
                        "queue_admission_materialized_task_ids": sorted(
                            str(task_id) for task_id in queue_materialized_task_ids
                        ),
                    },
                )
            )

        queue_admitted_task_ids = _uuid_set_from_metadata_list(queue_admission, "admitted_execution_task_ids")

    task_repo = ExecutionTaskRepository(db)
    tasks_by_id = {task.id: task for task in task_repo.list_for_mission(mission_id=mission_id)}
    dispatch_ready_task_ids: list[str] = []
    not_ready_task_ids: list[str] = []
    blocked_task_ids: list[str] = []
    skipped_task_ids: list[str] = []
    queued_task_count = 0

    for task_id in materialized_task_ids:
        task = tasks_by_id.get(task_id)
        if task is None:
            blocked_task_ids.append(str(task_id))
            blockers.append(
                _runtime_dispatch_item(
                    task_id=task_id,
                    code="materialized_task_unavailable",
                    message="Materialized execution task row is missing or unavailable for this mission.",
                )
            )
            continue
        if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
            blocked_task_ids.append(str(task_id))
            blockers.append(
                _runtime_dispatch_item(
                    task_id=task_id,
                    code="materialized_task_scope_mismatch",
                    message="Materialized execution task is not owned by this tenant and mission.",
                    state=task.status,
                )
            )
            continue

        task_id_str = str(task.id)
        if task.status == ExecutionTaskState.QUEUED.value:
            queued_task_count += 1
            if task.id not in queue_admitted_task_ids:
                blocked_task_ids.append(task_id_str)
                blockers.append(
                    _runtime_dispatch_item(
                        task_id=task.id,
                        code="task_not_queue_admitted",
                        message="Queued materialized task is not present in current runtime queue admission admitted task IDs.",
                        state=task.status,
                    )
                )
                continue
            if _task_has_dispatch_task_type(task):
                dispatch_ready_task_ids.append(task_id_str)
                continue
            blocked_task_ids.append(task_id_str)
            blockers.append(
                _runtime_dispatch_item(
                    task_id=task.id,
                    code="queued_task_missing_task_type",
                    message="Queued materialized task lacks non-empty dispatcher task_type metadata.",
                    state=task.status,
                )
            )
            warnings.append(
                _runtime_dispatch_item(
                    task_id=task.id,
                    code="default_handler_not_allowed",
                    message="Dispatch readiness requires explicit task_type metadata and does not rely on fallback handlers.",
                    state=task.status,
                )
            )
            continue
        if task.status in {ExecutionTaskState.PLANNED.value, ExecutionTaskState.PENDING_REVIEW.value}:
            not_ready_task_ids.append(task_id_str)
            blockers.append(
                _runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_not_queued",
                    message="Materialized task has not been admitted to the runtime queue.",
                    state=task.status,
                )
            )
            continue
        if task.status in {
            ExecutionTaskState.CLAIMED.value,
            ExecutionTaskState.RUNNING.value,
            ExecutionTaskState.RECOVERING.value,
            ExecutionTaskState.BLOCKED.value,
        }:
            not_ready_task_ids.append(task_id_str)
            warnings.append(
                _runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_already_claimed_or_running",
                    message="Materialized task is already claimed, running, recovering, or blocked.",
                    state=task.status,
                )
            )
            continue
        if task.status in {ExecutionTaskState.CANCELLED.value, ExecutionTaskState.COMPLETED.value}:
            skipped_task_ids.append(task_id_str)
            warnings.append(
                _runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_terminal_skipped",
                    message="Terminal materialized task is not dispatchable and is skipped.",
                    state=task.status,
                )
            )
            continue
        if task.status in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}:
            blocked_task_ids.append(task_id_str)
            blockers.append(
                _runtime_dispatch_item(
                    task_id=task.id,
                    code="materialized_task_failed_or_dead_lettered",
                    message="Failed or dead-lettered materialized task is not dispatch-ready.",
                    state=task.status,
                )
            )
            continue

        blocked_task_ids.append(task_id_str)
        blockers.append(
            _runtime_dispatch_item(
                task_id=task.id,
                code="materialized_task_unknown_state",
                message="Materialized task has an unknown runtime state.",
                state=task.status,
            )
        )

    readiness_status = _runtime_dispatch_readiness_status(
        dispatch_ready_task_ids=dispatch_ready_task_ids,
        not_ready_task_ids=not_ready_task_ids,
        blocked_task_ids=blocked_task_ids,
        skipped_task_ids=skipped_task_ids,
    )
    precondition_blocker_codes = {
        "runtime_task_materialization_missing",
        "no_current_materialized_tasks",
        "runtime_queue_admission_missing",
        "runtime_queue_admission_not_admitted",
        "runtime_queue_admission_tenant_mismatch",
        "runtime_queue_admission_mission_mismatch",
        "queue_admission_materialization_mismatch",
    }
    if any(blocker.get("code") in precondition_blocker_codes for blocker in blockers):
        readiness_status = "blocked"
    elif blockers and readiness_status == "ready":
        readiness_status = "partial" if dispatch_ready_task_ids else "blocked"
    return RuntimeDispatchReadinessRead(
        mission_id=mission.id,
        tenant_id=mission.tenant_id,
        readiness_status=readiness_status,
        dispatch_ready_task_ids=dispatch_ready_task_ids,
        not_ready_task_ids=not_ready_task_ids,
        blocked_task_ids=blocked_task_ids,
        skipped_task_ids=skipped_task_ids,
        task_count=len(materialized_task_ids),
        queued_task_count=queued_task_count,
        materialization_reference=materialization_reference,
        queue_admission_reference=queue_admission_reference,
        runtime_authority=_runtime_dispatch_authority_flags(),
        blockers=blockers,
        warnings=warnings,
        checked_at=checked_at,
    )


@router.get("/{mission_id}/runtime-dispatch-readiness", response_model=RuntimeDispatchReadinessRead)
def read_mission_runtime_dispatch_readiness(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeDispatchReadinessRead:
    """Read queued materialized task readiness without dispatching workers."""
    return _build_runtime_dispatch_readiness(mission_id=mission_id, tenant_id=tenant_id, db=db)


@router.post("/{mission_id}/runtime-queue-admission", response_model=RuntimeQueueAdmissionResponse)
def runtime_queue_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, object]:
    """Queue eligible planned tasks from the current runtime task materialization."""
    tenant_id_str = str(tenant_id)
    mission_repo = MissionRepository(db)
    mission = mission_repo.lock_for_tenant(mission_id=mission_id, tenant_id=tenant_id_str)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")

    metadata = dict(mission.metadata_json or {})
    materialized_task_ids = _current_materialized_execution_task_ids(metadata)
    task_repo = ExecutionTaskRepository(db)
    tasks_by_id = {task.id: task for task in task_repo.list_for_mission(mission_id=mission_id)}

    tasks_to_queue: list[Any] = []
    already_queued_task_ids: list[str] = []
    blockers: list[dict[str, Any]] = []
    if not materialized_task_ids:
        blockers.append(
            _runtime_queue_admission_blocker(
                task_id=None,
                code="no_current_materialized_tasks",
                message="Mission has no current materialized execution tasks for queue admission.",
            )
        )
    for task_id in materialized_task_ids:
        task = tasks_by_id.get(task_id)
        if task is None:
            blockers.append(
                _runtime_queue_admission_blocker(
                    task_id=task_id,
                    code="materialized_task_missing",
                    message="Materialized execution task row was not found for this mission.",
                )
            )
            continue
        if task.tenant_id != tenant_id_str or task.mission_id != mission_id:
            blockers.append(
                _runtime_queue_admission_blocker(
                    task_id=task_id,
                    code="materialized_task_scope_mismatch",
                    message="Materialized execution task is not owned by this tenant and mission.",
                    state=task.status,
                )
            )
            continue
        if task.status == ExecutionTaskState.PLANNED.value:
            tasks_to_queue.append(task)
            continue
        if task.status == ExecutionTaskState.QUEUED.value:
            already_queued_task_ids.append(str(task.id))
            continue
        blockers.append(
            _runtime_queue_admission_blocker(
                task_id=task.id,
                code="materialized_task_not_queueable",
                message="Materialized execution task is not planned or already queued.",
                state=task.status,
            )
        )

    if tasks_to_queue:
        try:
            QuotaEnforcementService(db).check_and_record_task_creation(tenant_id, count=len(tasks_to_queue))
        except QuotaExceededError as exc:
            raise _quota_exceeded_response(exc) from exc

    coordinator = ExecutionCoordinator(db, queue)
    queued_task_ids: list[str] = []
    pending_review_task_ids: list[str] = []
    denied_tasks: list[dict[str, str | None]] = []
    for task in tasks_to_queue:
        try:
            result = coordinator.queue_task(tenant_id=tenant_id_str, task_id=task.id)
        except Exception as exc:
            blockers.append(
                _runtime_queue_admission_blocker(
                    task_id=task.id,
                    code="queue_task_failed",
                    message="Execution coordinator failed to queue the materialized task.",
                    state=task.status,
                    reason=str(exc),
                )
            )
            continue
        if result.ok:
            queued_task_ids.append(str(task.id))
            continue
        denied_task = {"task_id": str(task.id), "state": result.state, "reason": result.reason}
        denied_tasks.append(denied_task)
        if result.state == ExecutionTaskState.PENDING_REVIEW.value:
            pending_review_task_ids.append(str(task.id))
        blockers.append(
            _runtime_queue_admission_blocker(
                task_id=task.id,
                code="queue_task_blocked",
                message="Execution coordinator did not admit the materialized task to the queue.",
                state=result.state,
                reason=result.reason,
            )
        )

    now = datetime.now(UTC).isoformat()
    queue_admission_metadata = _build_runtime_queue_admission_metadata(
        mission_id=mission_id,
        tenant_id=tenant_id_str,
        materialized_task_ids=materialized_task_ids,
        planned_task_ids=[str(task.id) for task in tasks_to_queue],
        queued_task_ids=queued_task_ids,
        already_queued_task_ids=already_queued_task_ids,
        pending_review_task_ids=pending_review_task_ids,
        denied_tasks=denied_tasks,
        blockers=blockers,
        now=now,
    )
    metadata[MISSION_RUNTIME_QUEUE_ADMISSION_METADATA_KEY] = queue_admission_metadata
    mission_repo.update_metadata(mission=mission, metadata_json=metadata)
    return _runtime_queue_admission_response(queue_admission_metadata)


@router.get("/{mission_id}/runtime-admission", response_model=RuntimeAdmissionRead)
def read_mission_runtime_admission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> RuntimeAdmissionRead:
    """Read tenant-scoped graph-to-runtime admission metadata."""
    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found for tenant")
    if MISSION_RUNTIME_ADMISSION_METADATA_KEY not in (mission.metadata_json or {}):
        raise HTTPException(status_code=404, detail="mission runtime admission not found")
    return _runtime_admission_to_read(mission)


@router.post("/{mission_id}/queue", response_model=MissionQueueResponse)
def queue_mission(
    mission_id: UUID,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> dict[str, object]:
    """Queue all planned tasks for a mission.

    Enforces task creation quota before queuing. The quota check uses the
    actual number of tenant-owned planned tasks that will be enqueued — not a
    flat 1 — so that tenants cannot bypass max_tasks_per_month by batching
    large missions into a single call.

    Returns HTTP 429 with structured body if the tenant has reached their
    plan limit.
    """
    # --- Count tenant-owned planned tasks that will actually be enqueued ---
    task_repo = ExecutionTaskRepository(db)
    all_tasks = task_repo.list_for_mission(mission_id=mission_id)
    tenant_id_str = str(tenant_id)
    planned_tasks = [
        t for t in all_tasks if t.tenant_id == tenant_id_str and t.status == ExecutionTaskState.PLANNED.value
    ]
    planned_count = len(planned_tasks)

    # --- Early return: no tenant-owned planned tasks, nothing to do ---
    if planned_count == 0:
        return {
            "queued_task_ids": [],
            "pending_review_task_ids": [],
            "denied_tasks": [],
        }

    # --- Quota check: consume N quota units for N tenant-owned planned tasks ---
    try:
        QuotaEnforcementService(db).check_and_record_task_creation(tenant_id, count=planned_count)
    except QuotaExceededError as exc:
        raise _quota_exceeded_response(exc) from exc

    executor = MissionExecutor(db, ExecutionCoordinator(db, queue))
    try:
        summary = executor.queue_all_planned_tasks(tenant_id=tenant_id_str, mission_id=mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "queued_task_ids": [str(task_id) for task_id in summary.queued_task_ids],
        "pending_review_task_ids": [str(task_id) for task_id in summary.pending_review_task_ids],
        "denied_tasks": [
            {
                "task_id": str(item.task_id),
                "state": item.state,
                "reason": item.reason,
            }
            for item in summary.denied_tasks
        ],
    }
