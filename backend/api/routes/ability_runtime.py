from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.domain.audit_event import AuditEvent
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.enums import ExecutionTaskState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import Mission
from backend.queue.base import QueueAdapter
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)
from backend.services.tools.action_registry import ActionDefinition, get_default_action_registry
from backend.services.tools.schemas import SideEffectClass

router = APIRouter(prefix="/ability-runtime", tags=["ability-runtime"])

READ_SAFE_ACTIONS: set[str] = {
    "calendar.read",
    "sales.research",
    "sales.qualify",
    "sales.score_lead",
    "sales.recommend_next_action",
    "sales.draft_followup",
    "record.search",
    "record.read",
    # PR9: expose GTM low-risk (no side effect) for pilot under ability-runtime
    "gtm.lead_enrich",
    "gtm.email_draft",
    "retrieval.hybrid_search",
}

INTERNAL_WRITE_ACTIONS: set[str] = {
    "calendar.create_event",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
}

EXTERNAL_ACTIONS: set[str] = {
    "http.request",
    "provider.external_read",
    "webhook.dispatch",
    # PR9 pilot: high-risk GTM external side-effect actions (EXTERNAL_SEND/WRITE/PUBLISH)
    "gtm.email_send",
    "gtm.crm_upsert",
    "gtm.social_publish",
    # Gmail check (read)
    "gtm.email_check",
}

GTM_HIGH_RISK_ACTIONS: set[str] = {
    "gtm.email_send",
    "gtm.crm_upsert",
    "gtm.social_publish",
}

EXPOSED_ACTIONS: set[str] = READ_SAFE_ACTIONS | INTERNAL_WRITE_ACTIONS | EXTERNAL_ACTIONS


class AbilityActionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    provider: str
    side_effect_class: str
    enabled: bool
    label: str
    requires_authority: bool
    provider_mode: Literal["local", "external", "mixed"]


class AbilityActionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[AbilityActionRead]


class AbilityTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=160)
    input: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=1000)
    mission_objective: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, max_length=200)
    approved_by: str = Field(default="ability-runtime-ui", min_length=1, max_length=160)
    approval_reason: str = Field(default="User launched ability from product runtime UI.", min_length=1, max_length=500)

    @field_validator("action")
    @classmethod
    def normalize_action(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("action must be non-empty")
        return normalized


class AbilityTaskQueuedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    mission_id: uuid.UUID
    status: str
    action: str
    queue_status: str
    queue_reason: str | None = None


class AbilityTaskStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID
    mission_id: uuid.UUID | None
    title: str
    description: str | None
    status: str
    action: str | None
    metadata_json: dict[str, Any]
    lineage: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    audit: list[dict[str, Any]]


def _label_for_action(action_name: str) -> str:
    return action_name.replace(".", " ").replace("_", " ").title()


def _provider_mode(provider: str, side_effect_class: SideEffectClass) -> Literal["local", "external", "mixed"]:
    if side_effect_class.value.startswith("external_"):
        return "external"
    if provider.startswith("local"):
        return "local"
    return "mixed"


def _requires_runtime_authority(side_effect_class: SideEffectClass) -> bool:
    return side_effect_class.has_side_effect or side_effect_class.value.startswith("external_")


def _adapter_side_effect_classification(side_effect_class: SideEffectClass) -> str:
    """Map runtime tool side-effect classes onto the persisted adapter contract."""
    if side_effect_class == SideEffectClass.NONE:
        return "none"
    if side_effect_class == SideEffectClass.INTERNAL_READ:
        return "read_only"
    if side_effect_class == SideEffectClass.INTERNAL_WRITE:
        return "non_idempotent_write"
    if side_effect_class in {
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.EXTERNAL_PUBLISH,
    }:
        return side_effect_class.value
    return "external_side_effect"


def _action_definition(action_name: str) -> ActionDefinition:
    registry = get_default_action_registry()
    try:
        return registry.get(action_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_exposed_action(action_name: str) -> None:
    if action_name not in EXPOSED_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action {action_name!r} is not exposed by ability-runtime.",
        )


def _ensure_runtime_authority(
    *,
    db: Session,
    tenant_id: str,
    action_name: str,
    side_effect_class: SideEffectClass,
    approved_by: str,
) -> tuple[Capability | None, CapabilityAdapter | None]:
    if not _requires_runtime_authority(side_effect_class):
        return None, None

    suffix = uuid.uuid4().hex[:10]
    approval_required = side_effect_class.value in {
        SideEffectClass.EXTERNAL_WRITE.value,
        SideEffectClass.EXTERNAL_SEND.value,
        SideEffectClass.EXTERNAL_PUBLISH.value,
    }

    capability = Capability(
        tenant_id=tenant_id,
        name=f"runtime-{action_name}-{suffix}",
        version="1.0.0",
        description=f"Runtime authority generated for {action_name}.",
        supported_task_types=["tool.invoke", action_name],
        input_schema_hints={},
        output_schema_hints={},
        required_permissions=[],
        required_tools=[action_name],
        risk_level="medium",
        approval_requirements={
            "required": approval_required,
            "generated_by": "ability-runtime",
            "approved_by": approved_by,
        },
        evidence_expectations=[f"{action_name} evidence"],
        execution_constraints={},
        enabled=True,
        schema_version=1,
    )
    db.add(capability)
    db.flush()

    adapter = CapabilityAdapter(
        tenant_id=tenant_id,
        name=f"runtime-{action_name}-adapter-{suffix}",
        version="1.0.0",
        capability_id=capability.id,
        capability_name=capability.name,
        capability_version=capability.version,
        supported_task_types=["tool.invoke", action_name],
        input_contract={},
        output_contract={},
        required_permissions=[],
        required_tools=[action_name],
        execution_mode="queued",
        risk_level="medium",
        approval_requirements={
            "required": approval_required,
            "generated_by": "ability-runtime",
            "approved_by": approved_by,
        },
        evidence_expectations=[f"{action_name} evidence"],
        timeout_retry_hints={},
        idempotency_expectations={},
        side_effect_classification=_adapter_side_effect_classification(side_effect_class),
        enabled=True,
        schema_version=1,
    )
    db.add(adapter)
    db.flush()
    return capability, adapter


def _build_task_metadata(
    *,
    action_name: str,
    input_payload: dict[str, Any],
    side_effect_class: SideEffectClass,
    capability: Capability | None,
    adapter: CapabilityAdapter | None,
    request_body: AbilityTaskCreate,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "task_type": "tool.invoke",
        "launched_by": "ability-runtime",
        "tool_invocation": {
            "schema_version": 1,
            "action": action_name,
            "input": input_payload,
        },
    }

    if request_body.idempotency_key:
        metadata["tool_invocation"]["idempotency_key"] = request_body.idempotency_key

    if capability is not None:
        metadata["capability_reference"] = {"capability_id": str(capability.id)}
    if adapter is not None:
        metadata["adapter_reference"] = {"adapter_id": str(adapter.id)}

    if side_effect_class.has_side_effect:
        metadata["execution_constraints"] = {
            "side_effect_authorization": {
                "schema_version": 1,
                "allowed_actions": [action_name],
                "reason": request_body.approval_reason,
                "approved_by": request_body.approved_by,
            }
        }

    return metadata


def _lineage_to_read(record: LineageRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "mission_id": str(record.mission_id) if record.mission_id else None,
        "task_id": str(record.task_id) if record.task_id else None,
        "fleet_id": str(record.fleet_id) if record.fleet_id else None,
        "branch_id": str(record.branch_id) if record.branch_id else None,
        "worker_lease_id": str(record.worker_lease_id) if record.worker_lease_id else None,
        "relationship_type": record.relationship_type,
        "relationship_reason": record.relationship_reason,
        "metadata_json": record.metadata_json,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _evidence_to_read(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "mission_id": str(record.mission_id),
        "execution_task_id": str(record.execution_task_id) if record.execution_task_id else None,
        "capability_id": str(record.capability_id) if record.capability_id else None,
        "capability_adapter_id": str(record.capability_adapter_id) if record.capability_adapter_id else None,
        "evidence_type": record.evidence_type,
        "evidence_source": record.evidence_source,
        "summary": record.summary,
        "structured_payload": record.structured_payload,
        "artifact_references": record.artifact_references,
        "provenance_metadata": record.provenance_metadata,
        "trust_signal": record.trust_signal,
        "confidence": record.confidence,
        "collection_status": record.collection_status,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _audit_to_read(record: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "tenant_id": record.tenant_id,
        "mission_id": str(record.mission_id) if record.mission_id else None,
        "category": record.category,
        "action": record.action,
        "actor": record.actor,
        "details": record.details,
        "payload_json": record.payload_json,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


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

    # PR9 pilot harness: explicit side_effect_authorization + guardian role enforcement
    # for high-risk GTM EXTERNAL actions (email_send, crm_upsert, social_publish).
    # Uses body.approved_by (must reference guardian per GUARDIAN_ROLE_CONTRACT.may_approve_side_effects=True).
    # This augments the always-written execution_constraints.side_effect_authorization envelope
    # (for has_side_effect) and the downstream ToolRuntimeAuthority + capability_validation + side_effect_authorized checks.
    # High-risk GTM also set requires_human_review to engage policy paths for pilot.
    if action_name in GTM_HIGH_RISK_ACTIONS:
        approved = (body.approved_by or "").strip().lower()
        if "guardian" not in approved:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"High-risk GTM action {action_name} requires explicit guardian role approval. "
                    "approved_by must reference 'guardian' (guardian role contract)."
                ),
            )

    try:
        quota.check_and_record_mission_creation(tenant_id)
        quota.check_and_record_task_creation(tenant_id)
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

    capability, adapter = _ensure_runtime_authority(
        db=db,
        tenant_id=str(tenant_id),
        action_name=action.name,
        side_effect_class=side_effect_class,
        approved_by=body.approved_by,
    )

    mission = Mission(
        tenant_id=str(tenant_id),
        objective=body.mission_objective or f"Ability runtime task: {action.name}",
        status="running",
        metadata_json={
            "schema_version": 1,
            "source": "ability-runtime",
            "action": action.name,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    db.add(mission)
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
            side_effect_class=side_effect_class,
            capability=capability,
            adapter=adapter,
            request_body=body,
        ),
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=action_name in GTM_HIGH_RISK_ACTIONS,
    )
    db.add(task)
    db.flush()

    queued = ExecutionCoordinator(db, queue).queue_task(
        tenant_id=str(tenant_id),
        task_id=task.id,
    )
    if not queued.ok:
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
