from __future__ import annotations

import uuid as _uuid
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.mission import (
    MISSION_INTAKE_METADATA_KEY,
    MISSION_PLAN_METADATA_KEY,
    Mission,
    build_mission_intake_metadata,
    build_mission_plan_metadata,
)
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_executor import MissionExecutor
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/missions", tags=["missions"])

MissionPriority = Literal["low", "normal", "high", "urgent"]
MissionPlanningStatus = Literal["draft", "in_review", "approved", "rejected", "superseded"]
MissionRiskLevel = Literal["low", "medium", "high", "critical"]
MissionApprovalGateStatus = Literal["not_required", "required", "approved", "rejected"]


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


class MissionQueueResponse(BaseModel):
    queued_task_ids: list[str]
    pending_review_task_ids: list[str]
    denied_tasks: list[dict[str, str | None]]


def _normalize_unique_string_list(value: list[str]) -> list[str]:
    normalized = [item.strip() for item in value]
    if any(not item for item in normalized):
        raise ValueError("list entries must be non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("list entries must be unique")
    return normalized


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
