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
from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, Mission, build_mission_intake_metadata
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.mission_executor import MissionExecutor
from backend.services.quota_enforcement import QuotaEnforcementService, QuotaExceededError

router = APIRouter(prefix="/missions", tags=["missions"])

MissionPriority = Literal["low", "normal", "high", "urgent"]


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
