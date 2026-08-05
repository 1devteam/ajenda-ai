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
from backend.services.mission_composition.contracts import (
    Clarification,
    Contradiction,
    MissionCompositionRecord,
    SendPolicy,
    StructuredPolicy,
    SuccessCriterion,
    TargetEntity,
    TimingConstraint,
)
from backend.services.mission_composition.interpretation.review import reviewed_interpretation_payload
from backend.services.mission_composition.service import (
    MissionCompositionError,
    MissionCompositionService,
)

router = APIRouter(prefix="/missions", tags=["mission-composition"])


class ComposeMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exact raw instruction (frontend validates non-empty with trim but must not strip).
    instruction: str = Field(min_length=1, max_length=8000)
    interpretation_thread_id: str | None = Field(default=None, max_length=80)


class ReviewedInterpretationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpreted_instruction: str
    requested_outcomes: list[str]
    unsupported_outcomes: list[str]
    requested_quantity: int | None
    send_policy: SendPolicy
    contact_policy: StructuredPolicy
    publish_policy: StructuredPolicy
    write_policy: StructuredPolicy
    target_entities: list[TargetEntity]
    timing_constraints: list[TimingConstraint]
    constraints: list[str]
    forbidden_outcomes: list[str]
    success_criteria: list[SuccessCriterion]
    approval_preference: str
    context_requirements: list[str]
    clarifications: list[Clarification]
    contradictions: list[Contradiction]


class ComposeMissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    interpretation_thread_id: str
    proposal_status: str = "interpretation_ready"
    interpreted_instruction: str
    interpretation_fingerprint: str
    mission_brief: ReviewedInterpretationResponse
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
    grants_execution_authority: bool = False
    authority_class: str = "read_model"


class ConfirmCompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interpretation_fingerprint: str = Field(min_length=8, max_length=80)
    interpretation_confirmed: bool
    idempotency_key: str = Field(min_length=1, max_length=200)


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
    """Resolve actor identity from the request principal.

    Production ``Principal`` exposes ``subject_id`` (not ``subject``/``sub``).
    """

    principal = getattr(request.state, "principal", None)
    if principal is None:
        return None
    for attr in ("subject_id", "subject", "sub", "member_id", "user_id"):
        value = getattr(principal, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _to_compose_response(record: MissionCompositionRecord) -> ComposeMissionResponse:
    verticals = sorted({item.vertical_key for item in record.job_assignments})
    return ComposeMissionResponse(
        proposal_id=record.proposal_id,
        interpretation_thread_id=record.interpretation_thread_id,
        proposal_status=str(record.proposal_status),
        interpreted_instruction=record.normalized_instruction or record.intent.normalized_instruction,
        interpretation_fingerprint=record.interpretation_fingerprint,
        mission_brief=ReviewedInterpretationResponse.model_validate(reviewed_interpretation_payload(record.intent)),
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
        grants_execution_authority=False,
        authority_class="read_model",
    )


_INTERPRETER_TRANSPORT_CODES = frozenset(
    {
        "INTERPRETER_DISABLED",
        "INTERPRETER_NOT_CONFIGURED",
        "INTERPRETER_ENDPOINT_NOT_ALLOWED",
        "INTERPRETER_TIMEOUT",
        "INTERPRETER_UNAVAILABLE",
        "INTERPRETER_INVALID_OUTPUT",
    }
)


def _map_error(exc: MissionCompositionError) -> HTTPException:
    status = 400
    if exc.code in {"PROPOSAL_NOT_FOUND"}:
        status = 404
    elif exc.code in {"QUOTA_EXCEEDED"}:
        status = 402
    elif exc.code in {
        "INTAKE_QUALITY",
        "NO_RUNTIME_ACTIONS",
        "PROPOSAL_NOT_READY",
        "INTERPRETATION_CONFIRMATION_REQUIRED",
        "INTERPRETATION_FINGERPRINT_MISMATCH",
        "INTERPRETATION_RECORD_INVALID",
        "CONFIRMED_INTERPRETATION_REQUIRED",
        "IDEMPOTENCY_KEY_REQUIRED",
        # Model-output/grounding failures are user-revisable interpretation
        # problems, not platform outages.
        "INTERPRETER_UNGROUNDED_OUTPUT",
        "INTERPRETER_DROPPED_RECIPIENT",
        "INTERPRETER_DROPPED_URL",
        "INTERPRETER_DROPPED_QUANTITY",
        "INTERPRETER_INVENTED_RECIPIENT",
        "INTERPRETER_INVENTED_URL",
        "INTERPRETER_INVENTED_QUANTITY",
        "INSTRUCTION_REQUIRED",
        "INSTRUCTION_TOO_LONG",
    }:
        status = 422
    elif exc.code in _INTERPRETER_TRANSPORT_CODES or exc.code.startswith("INTERPRETER_"):
        # Unknown INTERPRETER_* codes fail closed as unavailable rather than 400.
        status = 503
    elif exc.code in {
        "PROPOSAL_PERSIST_FAILED",
        "PROPOSAL_STORE_UNAVAILABLE",
        "CONFIRM_RECEIPT_PERSIST_FAILED",
    }:
        status = 503
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
        record = service.compose(
            tenant_id=str(tenant_id),
            instruction=body.instruction,
            actor_id=_actor_id(request),
            interpretation_thread_id=body.interpretation_thread_id,
        )
    except MissionCompositionError as exc:
        raise _map_error(exc) from exc
    return _to_compose_response(record)


@router.post("/proposals/{proposal_id}/confirm", response_model=ConfirmCompositionResponse)
def confirm_composition_proposal(
    proposal_id: str,
    request: Request,
    body: ConfirmCompositionRequest,
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
    try:
        result = service.confirm(
            tenant_id=str(tenant_id),
            proposal_id=proposal_id,
            interpretation_fingerprint=body.interpretation_fingerprint,
            interpretation_confirmed=body.interpretation_confirmed,
            actor_id=_actor_id(request),
            idempotency_key=body.idempotency_key,
        )
    except MissionCompositionError as exc:
        raise _map_error(exc) from exc
    return ConfirmCompositionResponse(**result)
