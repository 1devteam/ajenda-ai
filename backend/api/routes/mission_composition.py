"""Mission Composition API (ADR-0008).

POST /v1/missions/compose — read-only proposal (no runtime).
POST /v1/missions/proposals/{proposal_id}/confirm — intake + plan + graph only.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.permissions import Permission
from backend.services.mission_composition.contracts import MissionCompositionRecord
from backend.services.mission_composition.service import (
    MissionCompositionError,
    MissionCompositionService,
)

router = APIRouter(prefix="/missions", tags=["mission-composition"])


class ComposeMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=8000)


class ComposeMissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    instruction: str
    mission_brief: dict[str, Any]
    assigned_verticals: list[str]
    jobs: list[dict[str, Any]]
    selected_abilities: list[dict[str, Any]]
    forbidden_actions: list[str]
    allowed_actions: list[str]
    allowed_actions_provenance: dict[str, Any]
    missing_connections: list[dict[str, Any]]
    approval_gates: list[str]
    planned_steps: list[dict[str, Any]]
    task_graph_preview: dict[str, Any]
    clarifications: list[dict[str, Any]]
    ready_to_start: bool
    composition: dict[str, Any]
    grants_execution_authority: bool = False
    authority_class: str = "read_model"


class ConfirmCompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    composition: dict[str, Any] | None = None


class ConfirmCompositionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str
    proposal_id: str
    plan_id: str
    allowed_actions: list[str]
    forbidden_actions: list[str]
    task_graph: dict[str, Any]
    ready_to_start: bool
    runtime_queued: bool
    grants_execution_authority: bool
    next_steps: list[str]


def _actor_id(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return None
    subject = getattr(principal, "subject", None) or getattr(principal, "sub", None)
    if isinstance(subject, str) and subject.strip():
        return subject.strip()
    return None


def _to_compose_response(record: MissionCompositionRecord) -> ComposeMissionResponse:
    verticals = sorted({item.vertical_key for item in record.job_assignments})
    return ComposeMissionResponse(
        proposal_id=record.proposal_id,
        instruction=record.instruction,
        mission_brief={
            "objective": record.intent.objective,
            "success_criteria": [item.model_dump(mode="json") for item in record.intent.success_criteria],
            "constraints": list(record.intent.constraints),
            "approval_preference": record.intent.approval_preference,
            "target_entities": [item.model_dump(mode="json") for item in record.intent.target_entities],
        },
        assigned_verticals=verticals,
        jobs=[item.model_dump(mode="json") for item in record.job_assignments],
        selected_abilities=[item.model_dump(mode="json") for item in record.ability_selections],
        forbidden_actions=list(record.forbidden_actions),
        allowed_actions=list(record.allowed_actions),
        allowed_actions_provenance=record.allowed_actions_provenance.model_dump(mode="json"),
        missing_connections=list(record.missing_connections),
        approval_gates=list(record.approval_gates),
        planned_steps=[item.model_dump(mode="json") for item in record.planned_steps],
        task_graph_preview=dict(record.task_graph_preview),
        clarifications=[item.model_dump(mode="json") for item in record.clarifications],
        ready_to_start=record.ready_to_start,
        composition=record.model_dump(mode="json"),
        grants_execution_authority=False,
        authority_class="read_model",
    )


def _map_error(exc: MissionCompositionError) -> HTTPException:
    status = 400
    if exc.code in {"PROPOSAL_NOT_FOUND"}:
        status = 404
    elif exc.code in {"QUOTA_EXCEEDED"}:
        status = 402
    elif exc.code in {"INTAKE_QUALITY", "NO_RUNTIME_ACTIONS"}:
        status = 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.post("/compose", response_model=ComposeMissionResponse)
def compose_mission(
    body: ComposeMissionRequest,
    request: Request,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ComposeMissionResponse:
    """Compose a mission proposal from plain language without creating runtime state.

    Read-model / declarative only: no ExecutionTask, queue message, lease, or
    provider side-effect calls.
    """
    require_route_permission(request=request, db=db, permission=Permission.MISSION_CREATE, tenant_id=tenant_id)
    service = MissionCompositionService(db)
    try:
        record = service.compose(tenant_id=str(tenant_id), instruction=body.instruction)
    except MissionCompositionError as exc:
        raise _map_error(exc) from exc
    return _to_compose_response(record)


@router.post("/proposals/{proposal_id}/confirm", response_model=ConfirmCompositionResponse)
def confirm_composition_proposal(
    proposal_id: str,
    request: Request,
    body: ConfirmCompositionRequest | None = None,
    tenant_id: _uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> ConfirmCompositionResponse:
    """Confirm a composition proposal into mission intake + plan + task graph.

    Governed mutation only. Does not queue runtime work. Canonical queue path
    remains POST /v1/missions/{mission_id}/runtime-queue-admission.
    """
    require_route_permission(request=request, db=db, permission=Permission.MISSION_CREATE, tenant_id=tenant_id)
    # Plan/graph write also requires manage in mission routes; require both.
    require_route_permission(request=request, db=db, permission=Permission.MISSION_MANAGE, tenant_id=tenant_id)
    service = MissionCompositionService(db)
    composition = body.composition if body is not None else None
    try:
        result = service.confirm(
            tenant_id=str(tenant_id),
            proposal_id=proposal_id,
            composition=composition,
            actor_id=_actor_id(request),
        )
    except MissionCompositionError as exc:
        raise _map_error(exc) from exc
    return ConfirmCompositionResponse(**result)
