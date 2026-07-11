"""Vertical ops API — mission templates on the existing runtime spine (ADR-0007).

Authority:
- GET templates: read_model / declarative catalog (Phase B + Phase C)
- POST apply: governed_mutation (plan/graph; Phase B may create planned ExecutionTasks)
- POST queue / create-with-queue: runtime admission only via VerticalOpsTemplateService
  → ExecutionCoordinator (no TaskDispatcher, WorkerLoop, or Celery)
- Phase C templates are plan-only; queue fails closed until providers prove safe

Does not grant execution authority from declarative pack/role records alone.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.domain.compliance import is_supported_jurisdiction
from backend.domain.mission import Mission
from backend.queue.base import QueueAdapter
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.abilities.role_contracts import RoleName
from backend.services.operating_charter import (
    OperatingCharterViolation,
    assert_action_allowed,
    load_operating_charter,
)
from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import CredentialReference
from backend.services.vertical_ops.plan_templates import (
    get_vertical_mission_template,
    list_vertical_mission_templates,
    template_step_side_effect,
)
from backend.services.vertical_ops.template_service import (
    VERTICAL_TEMPLATE_METADATA_KEY,
    VerticalOpsTemplateService,
    VerticalTemplateApplyResult,
    VerticalTemplateQueueResult,
)

router = APIRouter(prefix="/vertical-ops", tags=["vertical-ops"])

_HIGH_RISK_QUEUE_ACTIONS = frozenset(
    {
        "gtm.email_send",
        "gtm.social_publish",
        "provider.external_read",
    }
)


class VerticalTemplateStepRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_key: str
    action_name: str
    title: str
    description: str
    depends_on: list[str]
    include_by_default: bool
    optional: bool
    side_effect_class: str
    binding_status: str


class VerticalTemplateRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str
    role_key: str
    pack_id: str
    pack_version: str
    display_name: str
    description: str
    objective_template: str
    phase: str
    allows_runtime_queue: bool
    authority_class: str
    grants_execution_authority: bool
    steps: list[VerticalTemplateStepRead]


class VerticalTemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    templates: list[VerticalTemplateRead]


class VerticalTemplateApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=160)
    selected_step_keys: list[str] | None = None
    step_inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    objective: str | None = Field(default=None, max_length=1000)
    approved_by: str = Field(default="vertical-ops-api", min_length=1, max_length=160)
    approval_reason: str = Field(
        default="Vertical ops Phase B template applied via API.",
        min_length=1,
        max_length=500,
    )
    idempotency_keys: dict[str, str] = Field(default_factory=dict)
    credential_references: dict[str, CredentialReference] = Field(default_factory=dict)
    jurisdiction: str | None = Field(default=None, max_length=64)
    queue: bool = False

    @field_validator("template_id", "approved_by", "approval_reason")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("jurisdiction")
    @classmethod
    def validate_jurisdiction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("jurisdiction must be non-empty when provided")
        if not is_supported_jurisdiction(stripped):
            raise ValueError("unsupported jurisdiction")
        return stripped


class VerticalTemplateCreateMissionRequest(VerticalTemplateApplyRequest):
    """Create a mission and apply a Phase B template in one request."""

    mission_objective: str | None = Field(default=None, max_length=1000)


class VerticalTemplateQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_ids: list[uuid.UUID] | None = None


class VerticalTaskQueueOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    ok: bool
    state: str
    reason: str | None = None


class VerticalTemplateApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: uuid.UUID
    template_id: str
    created_task_ids: list[uuid.UUID]
    queued: bool
    queue_outcomes: list[VerticalTaskQueueOutcome] = Field(default_factory=list)
    authority_class: str
    grants_execution_authority: bool = False


def _template_to_read(template_id: str) -> VerticalTemplateRead:
    template = get_vertical_mission_template(template_id)
    steps = [
        VerticalTemplateStepRead(
            step_key=step.step_key,
            action_name=step.action_name,
            title=step.title,
            description=step.description,
            depends_on=list(step.depends_on),
            include_by_default=step.include_by_default,
            optional=step.optional,
            side_effect_class=template_step_side_effect(step.action_name, role_key=template.role_key).value,
            binding_status=template.resolve_binding(step.action_name).binding_status.value,
        )
        for step in template.steps
    ]
    return VerticalTemplateRead(
        template_id=template.template_id,
        role_key=template.role_key,
        pack_id=template.pack_id,
        pack_version=template.pack_version,
        display_name=template.display_name,
        description=template.description,
        objective_template=template.objective_template,
        phase=template.phase,
        allows_runtime_queue=template.allows_runtime_queue,
        authority_class=template.authority_class,
        grants_execution_authority=template.grants_execution_authority,
        steps=steps,
    )


def _principal_may_approve_high_risk(request: Request) -> bool:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return False
    allowed_roles = {RoleName.GUARDIAN.value, "admin", "tenant_admin"}
    return bool(allowed_roles.intersection(set(getattr(principal, "roles", ()) or ())))


def _selected_actions(template_id: str, selected_step_keys: list[str] | None) -> list[str]:
    template = get_vertical_mission_template(template_id)
    steps = template.selected_steps(selected_step_keys)
    return [step.action_name for step in steps]


def _enforce_quota_and_features(
    *,
    db: Session,
    tenant_id: uuid.UUID,
    actions: list[str],
    creating_mission: bool,
    task_count: int,
    role_key: str | None = None,
) -> None:
    quota = QuotaEnforcementService(db)
    quota.check_tenant_active(tenant_id)

    needs_runtime_feature = False
    needs_gtm = False
    for action_name in actions:
        side_effect = template_step_side_effect(action_name, role_key=role_key)
        if side_effect.has_side_effect or side_effect.value.startswith("external_"):
            needs_runtime_feature = True
        if action_name.startswith("gtm."):
            needs_gtm = True

    try:
        if needs_runtime_feature:
            quota.require_feature(tenant_id, "ability_runtime")
        if needs_gtm:
            quota.require_feature(tenant_id, "gtm")
        if creating_mission:
            quota.check_and_record_mission_creation(tenant_id)
        for _ in range(max(task_count, 0)):
            quota.check_and_record_task_creation(tenant_id)
    except FeatureNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "QUOTA_EXCEEDED",
                "field": exc.field,
                "limit": exc.limit,
                "current": exc.current,
                "plan": exc.plan,
                "message": (
                    f"You have reached the {exc.field} limit ({exc.limit}) "
                    f"for the {exc.plan!r} plan. Upgrade to continue."
                ),
            },
        ) from exc


def _enforce_high_risk_queue_gates(*, request: Request, actions: list[str], body: VerticalTemplateApplyRequest) -> None:
    """Role gate for high-risk actions. Credential presence is enforced by the service."""
    high_risk = [action for action in actions if action in _HIGH_RISK_QUEUE_ACTIONS]
    if not high_risk:
        return
    if not _principal_may_approve_high_risk(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk vertical template steps require guardian, admin, or tenant_admin "
                f"role. Actions: {', '.join(high_risk)}"
            ),
        )


def _enforce_operating_charter(*, db: Session, tenant_id: uuid.UUID | str, actions: list[str]) -> None:
    """Match ability-runtime: fail closed on never_do / prepare/perform charter gates."""
    if not actions:
        return
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=str(tenant_id))
    approved_facts = profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
    charter = load_operating_charter(approved_facts=approved_facts)
    registry = get_default_action_registry()
    for action_name in actions:
        try:
            definition = registry.get(action_name)
        except ValueError:
            # Catalog-only / deferred actions have no runtime handler; charter is N/A.
            continue
        try:
            assert_action_allowed(
                action_name=definition.name,
                side_effect_class=definition.side_effect_class,
                charter=charter,
            )
        except OperatingCharterViolation as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": exc.code, "message": exc.message, "action": exc.action},
            ) from exc


def _parse_stored_created_task_ids(template_meta: dict[str, Any]) -> tuple[uuid.UUID, ...]:
    stored = template_meta.get("created_task_ids") or []
    if not isinstance(stored, list) or not stored:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no created_task_ids on vertical template application",
        )
    try:
        return tuple(uuid.UUID(str(item)) for item in stored)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid created_task_ids on vertical template application",
        ) from exc


def _resolve_queue_task_ids(
    *,
    body_task_ids: list[uuid.UUID] | None,
    template_meta: dict[str, Any],
) -> tuple[uuid.UUID, ...]:
    """Restrict queue admission to the applied template task set only."""
    allowed = _parse_stored_created_task_ids(template_meta)
    if body_task_ids is None:
        return allowed
    requested = tuple(body_task_ids)
    if not requested:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_ids must be non-empty when provided",
        )
    allowed_set = set(allowed)
    unknown = [str(task_id) for task_id in requested if task_id not in allowed_set]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "task_ids must be a subset of vertical_ops_template.created_task_ids; "
                f"unknown ids: {', '.join(unknown)}"
            ),
        )
    # Preserve caller order, de-dupe while validating membership.
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for task_id in requested:
        if task_id not in seen:
            seen.add(task_id)
            ordered.append(task_id)
    return tuple(ordered)


def _credential_refs_as_dict(
    refs: dict[str, CredentialReference],
) -> dict[str, CredentialReference]:
    return dict(refs)


def _apply_response(
    *,
    applied: VerticalTemplateApplyResult,
    queued: VerticalTemplateQueueResult | None,
) -> VerticalTemplateApplyResponse:
    outcomes: list[VerticalTaskQueueOutcome] = []
    if queued is not None:
        for result in queued.results:
            outcomes.append(
                VerticalTaskQueueOutcome(
                    task_id=result.task_id,
                    ok=result.ok,
                    state=result.state,
                    reason=result.reason,
                )
            )
    return VerticalTemplateApplyResponse(
        mission_id=applied.mission_id,
        template_id=applied.template_id,
        created_task_ids=list(applied.created_task_ids),
        queued=queued is not None,
        queue_outcomes=outcomes,
        authority_class="runtime_authoritative" if queued is not None else applied.authority_class,
        grants_execution_authority=False,
    )


@router.get("/templates", response_model=VerticalTemplateListResponse)
def list_templates(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> VerticalTemplateListResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    templates = [_template_to_read(template.template_id) for template in list_vertical_mission_templates()]
    return VerticalTemplateListResponse(templates=templates)


@router.get("/templates/{template_id}", response_model=VerticalTemplateRead)
def get_template(
    template_id: str,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> VerticalTemplateRead:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    try:
        return _template_to_read(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/missions",
    response_model=VerticalTemplateApplyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_mission_from_template(
    body: VerticalTemplateCreateMissionRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> VerticalTemplateApplyResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.MISSION_MANAGE,
        tenant_id=tenant_id,
    )
    if body.queue:
        require_route_permission(
            request=request,
            db=db,
            permission=Permission.EXECUTION_QUEUE,
            tenant_id=tenant_id,
        )

    try:
        actions = _selected_actions(body.template_id, body.selected_step_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    service = VerticalOpsTemplateService()
    if body.queue:
        try:
            service.ensure_runtime_queue_allowed(template_id=body.template_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _enforce_high_risk_queue_gates(request=request, actions=actions, body=body)

    try:
        bundle = service.build_bundle(
            template_id=body.template_id,
            step_inputs=body.step_inputs,
            selected_step_keys=body.selected_step_keys,
            objective=body.objective or body.mission_objective,
            approved_by=body.approved_by,
            approval_reason=body.approval_reason,
            idempotency_keys=body.idempotency_keys,
            credential_references=_credential_refs_as_dict(body.credential_references),
            jurisdiction=body.jurisdiction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Charter gates apply whenever runtime-bound tasks will be materialized or queued.
    if bundle.allows_runtime_queue:
        _enforce_operating_charter(db=db, tenant_id=tenant_id, actions=actions)

    _enforce_quota_and_features(
        db=db,
        tenant_id=tenant_id,
        actions=actions if bundle.allows_runtime_queue else [],
        creating_mission=True,
        task_count=len(bundle.planned_tasks),
        role_key=bundle.role_key,
    )

    from backend.services.abilities.vertical_role_catalog import get_vertical_role

    role = get_vertical_role(bundle.role_key)
    mission = Mission(
        tenant_id=str(tenant_id),
        objective=body.mission_objective or body.objective or bundle.objective,
        status="planned",
        metadata_json={
            "schema_version": 1,
            "source": "vertical-ops",
            "template_id": body.template_id,
            "phase": bundle.phase,
            "allows_runtime_queue": bundle.allows_runtime_queue,
        },
        compliance_category=role.compliance_category,
        jurisdiction=body.jurisdiction or role.default_jurisdiction,
    )
    db.add(mission)
    db.flush()

    try:
        if body.queue:
            applied, queued = service.apply_and_queue(
                session=db,
                queue=queue,
                mission=mission,
                template_id=body.template_id,
                step_inputs=body.step_inputs,
                selected_step_keys=body.selected_step_keys,
                objective=body.objective or body.mission_objective,
                approved_by=body.approved_by,
                approval_reason=body.approval_reason,
                idempotency_keys=body.idempotency_keys,
                credential_references=_credential_refs_as_dict(body.credential_references),
                jurisdiction=body.jurisdiction,
            )
            # If all blocked, still return 201 with outcomes (policy review is valid).
            db.commit()
            return _apply_response(applied=applied, queued=queued)

        applied = service.apply_to_mission(
            session=db,
            mission=mission,
            template_id=body.template_id,
            step_inputs=body.step_inputs,
            selected_step_keys=body.selected_step_keys,
            objective=body.objective or body.mission_objective,
            approved_by=body.approved_by,
            approval_reason=body.approval_reason,
            idempotency_keys=body.idempotency_keys,
            credential_references=_credential_refs_as_dict(body.credential_references),
            jurisdiction=body.jurisdiction,
        )
        db.commit()
        return _apply_response(applied=applied, queued=None)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/missions/{mission_id}/apply",
    response_model=VerticalTemplateApplyResponse,
    status_code=status.HTTP_200_OK,
)
def apply_template_to_mission(
    mission_id: uuid.UUID,
    body: VerticalTemplateApplyRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> VerticalTemplateApplyResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.MISSION_MANAGE,
        tenant_id=tenant_id,
    )
    if body.queue:
        require_route_permission(
            request=request,
            db=db,
            permission=Permission.EXECUTION_QUEUE,
            tenant_id=tenant_id,
        )

    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mission not found for tenant")

    try:
        actions = _selected_actions(body.template_id, body.selected_step_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    service = VerticalOpsTemplateService()
    if body.queue:
        try:
            service.ensure_runtime_queue_allowed(template_id=body.template_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _enforce_high_risk_queue_gates(request=request, actions=actions, body=body)

    try:
        bundle = service.build_bundle(
            template_id=body.template_id,
            step_inputs=body.step_inputs,
            selected_step_keys=body.selected_step_keys,
            objective=body.objective,
            approved_by=body.approved_by,
            approval_reason=body.approval_reason,
            idempotency_keys=body.idempotency_keys,
            credential_references=_credential_refs_as_dict(body.credential_references),
            jurisdiction=body.jurisdiction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if bundle.allows_runtime_queue:
        _enforce_operating_charter(db=db, tenant_id=tenant_id, actions=actions)

    _enforce_quota_and_features(
        db=db,
        tenant_id=tenant_id,
        actions=actions if bundle.allows_runtime_queue else [],
        creating_mission=False,
        task_count=len(bundle.planned_tasks),
        role_key=bundle.role_key,
    )

    try:
        if body.queue:
            applied, queued = service.apply_and_queue(
                session=db,
                queue=queue,
                mission=mission,
                template_id=body.template_id,
                step_inputs=body.step_inputs,
                selected_step_keys=body.selected_step_keys,
                objective=body.objective,
                approved_by=body.approved_by,
                approval_reason=body.approval_reason,
                idempotency_keys=body.idempotency_keys,
                credential_references=_credential_refs_as_dict(body.credential_references),
                jurisdiction=body.jurisdiction,
            )
            db.commit()
            return _apply_response(applied=applied, queued=queued)

        applied = service.apply_to_mission(
            session=db,
            mission=mission,
            template_id=body.template_id,
            step_inputs=body.step_inputs,
            selected_step_keys=body.selected_step_keys,
            objective=body.objective,
            approved_by=body.approved_by,
            approval_reason=body.approval_reason,
            idempotency_keys=body.idempotency_keys,
            credential_references=_credential_refs_as_dict(body.credential_references),
            jurisdiction=body.jurisdiction,
        )
        db.commit()
        return _apply_response(applied=applied, queued=None)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/missions/{mission_id}/queue",
    response_model=VerticalTemplateApplyResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_applied_template_tasks(
    mission_id: uuid.UUID,
    body: VerticalTemplateQueueRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> VerticalTemplateApplyResponse:
    """Queue previously applied vertical-ops planned tasks via ExecutionCoordinator only."""

    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_QUEUE,
        tenant_id=tenant_id,
    )

    mission = MissionRepository(db).get_for_tenant(mission_id=mission_id, tenant_id=str(tenant_id))
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mission not found for tenant")

    template_meta = (mission.metadata_json or {}).get(VERTICAL_TEMPLATE_METADATA_KEY)
    if not isinstance(template_meta, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="mission has no vertical_ops_template application metadata",
        )

    template_id = template_meta.get("template_id")
    if not isinstance(template_id, str) or not template_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="vertical template_id missing on mission")

    service = VerticalOpsTemplateService()
    try:
        service.ensure_runtime_queue_allowed(template_id=template_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if template_meta.get("allows_runtime_queue") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"template {template_id!r} is plan-only; runtime queue is disabled",
        )

    task_ids = _resolve_queue_task_ids(body_task_ids=body.task_ids, template_meta=template_meta)

    # High-risk + charter gates based on selected template steps currently applied.
    selected = template_meta.get("selected_step_keys")
    selected_keys = list(selected) if isinstance(selected, list) else None
    try:
        actions = _selected_actions(template_id, selected_keys)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _enforce_operating_charter(db=db, tenant_id=tenant_id, actions=actions)

    # Synthetic body for credential checks is not available on re-queue; enforce role only.
    high_risk = [action for action in actions if action in _HIGH_RISK_QUEUE_ACTIONS]
    if high_risk and not _principal_may_approve_high_risk(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk vertical template steps require guardian, admin, or tenant_admin "
                f"role. Actions: {', '.join(high_risk)}"
            ),
        )

    queued = service.queue_planned_tasks(
        session=db,
        queue=queue,
        tenant_id=str(tenant_id),
        task_ids=task_ids,
        template_id=template_id,
    )
    db.commit()

    applied = VerticalTemplateApplyResult(
        mission_id=mission.id,
        template_id=template_id,
        created_task_ids=task_ids,
        plan_contract={},
        task_graph={},
    )
    return _apply_response(applied=applied, queued=queued)
