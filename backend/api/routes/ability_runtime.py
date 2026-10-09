from datetime import datetime, UTC
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.api.routes.ability_runtime_authority import (
    _ensure_runtime_authority,
    _LaunchAuthority,
    _principal_may_approve_gtm_side_effects,
    _resolve_launch_authority,
    _resolve_runtime_authority,
)
from backend.api.routes.ability_runtime_contracts import (
    AbilityActionListResponse,
    AbilityActionRead,
    AbilityTaskCreate,
    AbilityTaskQueuedResponse,
    AbilityTaskStatusResponse,
)
from backend.api.routes.ability_runtime_policy import (
    _action_definition,
    _assert_action_allowed_for_mission,
    _label_for_action,
    _provider_mode,
    _requires_runtime_authority,
    _validate_exposed_action,
    CREDENTIALED_EXTERNAL_READ_ACTIONS,
    EXPOSED_ACTIONS,
    EXTERNAL_ACTIONS,
    GTM_HIGH_RISK_ACTIONS,
    GTM_HIGH_RISK_ACTIONS_REQUIRING_CREDENTIAL,
    INTERNAL_WRITE_ACTIONS,
    READ_SAFE_ACTIONS,
)
from backend.api.routes.ability_runtime_projection import (
    _audit_to_read,
    _build_task_metadata,
    _evidence_to_read,
    _lineage_to_read,
)
from backend.app.config import get_settings
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.domain.audit_event import AuditEvent
from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.queue.base import QueueAdapter
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.autonomy.disclaimer_catalog import catalog_entries_for_api
from backend.services.brain_capability_check import build_brain_capability_report
from backend.services.brain_mission_catalog import BRAIN_MISSIONS
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.operating_charter import (
    assert_action_allowed,
    charter_requires_human_review_for_launch,
    load_operating_charter,
    OperatingCharterViolation,
)
from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)
from backend.services.tools.action_registry import get_default_action_registry

__all__ = (
    "CREDENTIALED_EXTERNAL_READ_ACTIONS",
    "EXTERNAL_ACTIONS",
    "GTM_HIGH_RISK_ACTIONS",
    "INTERNAL_WRITE_ACTIONS",
    "READ_SAFE_ACTIONS",
    "AbilityTaskCreate",
    "_ensure_runtime_authority",
    "_requires_runtime_authority",
    "_resolve_launch_authority",
    "_resolve_runtime_authority",
    "launch_task",
)

router = APIRouter(prefix="/ability-runtime", tags=["ability-runtime"])
















@router.get("/actions", response_model=AbilityActionListResponse)
def list_actions(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> AbilityActionListResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )

    registry = get_default_action_registry()
    actions: list[AbilityActionRead] = []

    for action_name in sorted(EXPOSED_ACTIONS):
        try:
            definition = registry.get(action_name)
        except ValueError:
            continue

        side_effect_class = definition.side_effect_class
        actions.append(
            AbilityActionRead(
                name=definition.name,
                provider=definition.provider,
                side_effect_class=side_effect_class.value,
                enabled=True,
                label=_label_for_action(definition.name),
                requires_authority=_requires_runtime_authority(side_effect_class),
                provider_mode=_provider_mode(definition.provider, side_effect_class),
            )
        )

    return AbilityActionListResponse(actions=actions)


@router.get("/brain-missions")
def list_brain_missions(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, Any]:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    return {
        "schema_version": 1,
        "missions": list(BRAIN_MISSIONS),
    }


@router.get("/brain-capability-check")
def brain_capability_check(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, Any]:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    return build_brain_capability_report(session=db, tenant_id=str(tenant_id)).to_api()


@router.get("/disclaimers")
def list_disclaimers(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> dict[str, Any]:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    return {
        "schema_version": 1,
        "mode": get_settings().autonomy_disclaimer_mode,
        "disclaimers": catalog_entries_for_api(),
    }


@router.post("/tasks", response_model=AbilityTaskQueuedResponse, status_code=status.HTTP_202_ACCEPTED)
def launch_task(
    body: AbilityTaskCreate,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> AbilityTaskQueuedResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_QUEUE,
        tenant_id=tenant_id,
    )

    action_name = body.action
    _validate_exposed_action(action_name)
    action = _action_definition(action_name)
    side_effect_class = action.side_effect_class

    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=str(tenant_id))
    approved_facts = profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
    charter = load_operating_charter(approved_facts=approved_facts)
    try:
        assert_action_allowed(action_name=action_name, side_effect_class=side_effect_class, charter=charter)
    except OperatingCharterViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message, "action": exc.action},
        ) from exc

    # Defense-in-depth quota and feature gate for ability-runtime launched tasks.
    quota = QuotaEnforcementService(db)
    quota.check_tenant_active(tenant_id)
    if action_name in EXTERNAL_ACTIONS or _requires_runtime_authority(side_effect_class):
        try:
            quota.require_feature(tenant_id, "ability_runtime")
        except FeatureNotAvailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=str(exc),
            ) from exc
        except QuotaExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=str(exc),
            ) from exc

    # PR6: gate GTM actions behind feature (will be in pro+ plans)
    if action_name.startswith("gtm."):
        try:
            quota.require_feature(tenant_id, "gtm")
        except FeatureNotAvailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=str(exc),
            ) from exc

    launch_authority = _resolve_launch_authority(request=request, body=body, action_name=action_name)
    if not launch_authority.requires_human_review and charter_requires_human_review_for_launch(
        charter=charter, side_effect_class=side_effect_class
    ):
        launch_authority = _LaunchAuthority(
            approved_by=launch_authority.approved_by,
            approval_reason=launch_authority.approval_reason,
            requires_human_review=True,
            autonomy_acknowledgment=launch_authority.autonomy_acknowledgment,
        )

    # PR9 pilot harness: explicit side_effect_authorization + guardian role enforcement
    # for high-risk GTM EXTERNAL actions (email_send, crm_upsert, social_publish).
    # Informed autonomy (ADR-0005) may waive guardian + requires_human_review when a valid
    # autonomy_acknowledgment is present and AJENDA_AUTONOMY_DISCLAIMER_MODE is pilot/enforce.
    if action_name in GTM_HIGH_RISK_ACTIONS:
        if launch_authority.autonomy_acknowledgment is None and not _principal_may_approve_gtm_side_effects(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(f"High-risk GTM action {action_name} requires guardian, admin, or tenant_admin role."),
            )
        if action_name in GTM_HIGH_RISK_ACTIONS_REQUIRING_CREDENTIAL and body.credential_reference is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"High-risk GTM action {action_name} requires credential_reference in launch payload.",
            )
        if not (body.idempotency_key and body.idempotency_key.strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"High-risk GTM action {action_name} requires idempotency_key in launch payload.",
            )

    if (
        action_name in CREDENTIALED_EXTERNAL_READ_ACTIONS
        and body.credential_reference is not None
        and launch_authority.autonomy_acknowledgment is None
    ):
        if not _principal_may_approve_gtm_side_effects(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"External read action {action_name} with credential_reference "
                    "requires guardian, admin, or tenant_admin role."
                ),
            )

    try:
        if body.mission_id is None:
            quota.check_and_record_mission_creation(tenant_id)
        quota.check_and_record_task_creation(tenant_id)
    except QuotaExceededError as exc:
        from backend.api.errors import quota_exceeded_http

        raise quota_exceeded_http(exc) from exc

    if body.mission_id is not None:
        mission = MissionRepository(db).get_for_tenant(mission_id=body.mission_id, tenant_id=str(tenant_id))
        if mission is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="mission not found for tenant")
        _assert_action_allowed_for_mission(mission=mission, action_name=action_name)
        if mission.status == MissionState.PLANNED.value:
            mission.status = MissionState.RUNNING.value
    else:
        mission = Mission(
            tenant_id=str(tenant_id),
            objective=body.mission_objective or f"Ability runtime task: {action.name}",
            status=MissionState.RUNNING.value,
            metadata_json={
                "schema_version": 1,
                "source": "ability-runtime",
                "action": action.name,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        db.add(mission)
    capability, adapter = _resolve_runtime_authority(
        db=db,
        tenant_id=str(tenant_id),
        action_name=action.name,
        side_effect_class=side_effect_class,
        capability_id=body.capability_id,
        adapter_id=body.adapter_id,
    )
    db.flush()

    task = ExecutionTask(
        tenant_id=str(tenant_id),
        mission_id=mission.id,
        title=body.title or f"Run {action.name}",
        description=body.description or f"Ability runtime worker task for {action.name}.",
        status=ExecutionTaskState.PLANNED.value,
        metadata_json=_build_task_metadata(
            action_name=action.name,
            input_payload=body.input,
            capability=capability,
            adapter=adapter,
            request_body=body,
            autonomy_acknowledgment=launch_authority.autonomy_acknowledgment,
        ),
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=launch_authority.requires_human_review,
    )
    db.add(task)
    db.flush()

    if launch_authority.autonomy_acknowledgment is not None:
        db.add(
            AuditEvent(
                tenant_id=str(tenant_id),
                mission_id=mission.id,
                category="autonomy",
                action="autonomy_disclaimer_accepted",
                actor=launch_authority.approved_by,
                details=f"Accepted {launch_authority.autonomy_acknowledgment['disclaimer_id']} for {action_name}",
                payload_json={
                    "task_id": str(task.id),
                    "action": action_name,
                    **launch_authority.autonomy_acknowledgment,
                },
            )
        )

    queued = ExecutionCoordinator(db, queue).queue_task(
        tenant_id=str(tenant_id),
        task_id=task.id,
    )
    if not queued.ok:
        if queued.state == ExecutionTaskState.PENDING_REVIEW.value:
            db.commit()
            return AbilityTaskQueuedResponse(
                task_id=task.id,
                mission_id=mission.id,
                status=task.status,
                action=action.name,
                queue_status="review_required",
                queue_reason=queued.reason,
            )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=queued.reason or "Task was not accepted for runtime queueing.",
        )

    db.commit()
    return AbilityTaskQueuedResponse(
        task_id=task.id,
        mission_id=mission.id,
        status=task.status,
        action=action.name,
        queue_status="queued",
        queue_reason=queued.reason,
    )


@router.get("/tasks/{task_id}", response_model=AbilityTaskStatusResponse)
def get_task_status(
    task_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
) -> AbilityTaskStatusResponse:
    require_route_permission(
        request=request,
        db=db,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )

    task = db.get(ExecutionTask, task_id)
    if task is None or task.tenant_id != str(tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    lineage = list(
        db.scalars(
            select(LineageRecord)
            .where(LineageRecord.tenant_id == str(tenant_id))
            .where(LineageRecord.task_id == task_id)
            .order_by(LineageRecord.created_at.asc())
        )
    )
    evidence = list(
        db.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.tenant_id == str(tenant_id))
            .where(EvidenceRecord.execution_task_id == task_id)
            .order_by(EvidenceRecord.created_at.asc())
        )
    )
    recent_audit = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == str(tenant_id))
            .order_by(AuditEvent.created_at.desc())
            .limit(200)
        )
    )
    audit = [
        record
        for record in recent_audit
        if isinstance(record.payload_json, dict) and record.payload_json.get("task_id") == str(task_id)
    ]

    raw_invocation = task.metadata_json.get("tool_invocation")
    action_name = raw_invocation.get("action") if isinstance(raw_invocation, dict) else None

    return AbilityTaskStatusResponse(
        task_id=task.id,
        mission_id=task.mission_id,
        title=task.title,
        description=task.description,
        status=task.status,
        action=action_name,
        metadata_json=task.metadata_json,
        lineage=[_lineage_to_read(record) for record in lineage],
        evidence=[_evidence_to_read(record) for record in evidence],
        audit=[_audit_to_read(record) for record in audit],
    )


@router.post("/proofs/calendar-read", response_model=AbilityTaskQueuedResponse, status_code=status.HTTP_202_ACCEPTED)
def launch_calendar_read(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> AbilityTaskQueuedResponse:
    body = AbilityTaskCreate(
        action="calendar.read",
        input={"calendar_id": "primary", "limit": 10},
        title="Read primary calendar",
        mission_objective="Read calendar through runtime worker.",
    )
    return launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)


@router.post("/proofs/calendar-create", response_model=AbilityTaskQueuedResponse, status_code=status.HTTP_202_ACCEPTED)
def launch_calendar_create(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> AbilityTaskQueuedResponse:
    body = AbilityTaskCreate(
        action="calendar.create_event",
        input={
            "calendar_id": "primary",
            "title": "Ajenda runtime proof event",
            "start": "2026-06-16T10:00:00Z",
            "end": "2026-06-16T10:30:00Z",
            "attendees": [],
            "description": "Created through ability-runtime worker path.",
        },
        title="Create calendar proof event",
        mission_objective="Create calendar event through runtime worker.",
        approval_reason="User requested local calendar proof event creation.",
    )
    return launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)


@router.post("/proofs/sales-qualify", response_model=AbilityTaskQueuedResponse, status_code=status.HTTP_202_ACCEPTED)
def launch_sales_qualify(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> AbilityTaskQueuedResponse:
    body = AbilityTaskCreate(
        action="sales.qualify",
        input={
            "lead": {
                "company": "Blackvault Roofing",
                "role": "Owner",
                "intent": "Needs roofing lead generation",
                "email": "owner@example.com",
            },
            "context": {"intent": "Find more roofing leads"},
        },
        title="Qualify roofing lead",
        mission_objective="Qualify a roofing lead through runtime worker.",
    )
    return launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)


@router.post(
    "/proofs/sales-draft-followup", response_model=AbilityTaskQueuedResponse, status_code=status.HTTP_202_ACCEPTED
)
def launch_sales_draft_followup(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    db: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> AbilityTaskQueuedResponse:
    body = AbilityTaskCreate(
        action="sales.draft_followup",
        input={
            "recipient_name": "there",
            "topic": "roofing lead generation",
            "tone": "direct",
            "context": {"mission": "follow up with a potential roofing lead"},
        },
        title="Draft sales follow-up",
        mission_objective="Draft a sales follow-up through runtime worker.",
    )
    return launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)
