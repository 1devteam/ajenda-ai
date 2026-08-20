from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.config import get_settings
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.domain.audit_event import AuditEvent
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.domain.enums import ExecutionTaskState, MissionState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.lineage_record import LineageRecord
from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, Mission
from backend.queue.base import QueueAdapter
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.repositories.mission_repository import MissionRepository
from backend.services.abilities.role_contracts import RoleName
from backend.services.autonomy.disclaimer_catalog import (
    AutonomyPolicyError,
    action_tier,
    catalog_entries_for_api,
    parse_autonomy_acknowledgment,
    validate_autonomy_acknowledgment,
)
from backend.services.brain_capability_check import build_brain_capability_report
from backend.services.brain_mission_catalog import BRAIN_MISSIONS
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.operating_charter import (
    OperatingCharterViolation,
    assert_action_allowed,
    charter_requires_human_review_for_launch,
    load_operating_charter,
)
from backend.services.quota_enforcement import (
    FeatureNotAvailableError,
    QuotaEnforcementService,
    QuotaExceededError,
)
from backend.services.tools.action_registry import ActionDefinition, get_default_action_registry
from backend.services.tools.schemas import CredentialReference, SideEffectClass

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
    "web.research",
    "web.search",
    "web.page_read",
    "research.observe_contacts",
    "knowledge.retrieve_current",
    "decision.recommend_next_action",
    "web.browser_session",
    "crm.research",
    "crm.read",
}

INTERNAL_WRITE_ACTIONS: set[str] = {
    "calendar.create_event",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
}

EXTERNAL_ACTIONS: set[str] = {
    "http.request",
    "web.open_write",
    "provider.external_read",
    "linkedin.profile_read",
    "salesforce.soql_read",
    "google_calendar.events_read",
    "github.repo_read",
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

GTM_HIGH_RISK_ACTIONS_REQUIRING_CREDENTIAL: set[str] = {
    "gtm.email_send",
    "gtm.social_publish",
}

# Credentialed external reads require guardian approval before launch.
CREDENTIALED_EXTERNAL_READ_ACTIONS: set[str] = {
    "gtm.email_check",
    "sales.research",
    "crm.research",
    "crm.read",
    "linkedin.profile_read",
    "salesforce.soql_read",
    "google_calendar.events_read",
    "github.repo_read",
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
    mission_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)
    approved_by: str = Field(default="ability-runtime-ui", min_length=1, max_length=160)
    approval_reason: str = Field(default="User launched ability from product runtime UI.", min_length=1, max_length=500)
    credential_reference: CredentialReference | None = None
    capability_id: uuid.UUID | None = None
    adapter_id: uuid.UUID | None = None
    autonomy_acknowledgment: dict[str, Any] | None = None

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


def _mission_allowed_actions(metadata_json: dict[str, Any]) -> list[str]:
    intake = metadata_json.get(MISSION_INTAKE_METADATA_KEY)
    if not isinstance(intake, dict):
        return []
    raw_actions = intake.get("allowed_actions")
    if not isinstance(raw_actions, list):
        return []
    return [str(item).strip() for item in raw_actions if isinstance(item, str) and item.strip()]


def _assert_action_allowed_for_mission(*, mission: Mission, action_name: str) -> None:
    allowed_actions = _mission_allowed_actions(mission.metadata_json)
    if not allowed_actions:
        return
    registry = get_default_action_registry()
    try:
        definition = registry.get(action_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action {action_name!r} is not registered for mission-scoped launch.",
        ) from exc
    permitted_names = {definition.name, *definition.aliases}
    if not permitted_names.intersection(allowed_actions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "MISSION_ACTION_NOT_ALLOWED",
                "message": f"Action {action_name!r} is outside this mission's allowed_actions scope.",
                "allowed_actions": allowed_actions,
            },
        )


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


def _principal_may_approve_gtm_side_effects(request: Request) -> bool:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return False
    allowed_roles = {RoleName.GUARDIAN.value, "admin", "tenant_admin"}
    return bool(allowed_roles.intersection(set(getattr(principal, "roles", ()) or ())))


def _principal_subject_id(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return None
    return str(getattr(principal, "subject_id", "")).strip() or None


INFORMED_AUTONOMY_LAUNCH_ROLES = frozenset({"tenant_owner", "tenant_operator"})


def _principal_may_launch_informed_autonomy(request: Request) -> bool:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return False
    return bool(INFORMED_AUTONOMY_LAUNCH_ROLES.intersection(set(getattr(principal, "roles", ()) or ())))


@dataclass(slots=True)
class _LaunchAuthority:
    approved_by: str
    approval_reason: str
    requires_human_review: bool
    autonomy_acknowledgment: dict[str, Any] | None


def _resolve_launch_authority(
    *,
    request: Request,
    body: AbilityTaskCreate,
    action_name: str,
) -> _LaunchAuthority:
    settings = get_settings()
    mode = settings.autonomy_disclaimer_mode
    approved_by = body.approved_by
    approval_reason = body.approval_reason
    requires_human_review = action_name in GTM_HIGH_RISK_ACTIONS
    autonomy_payload: dict[str, Any] | None = None

    if mode in {"pilot", "enforce"} and body.autonomy_acknowledgment is not None:
        try:
            acknowledgment = parse_autonomy_acknowledgment(body.autonomy_acknowledgment)
            entry = validate_autonomy_acknowledgment(acknowledgment=acknowledgment, action_name=action_name)
        except AutonomyPolicyError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        principal_id = _principal_subject_id(request)
        if principal_id is None:
            from backend.api.errors import authentication_required_http

            raise authentication_required_http()
        if acknowledgment.principal_id != principal_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="autonomy_acknowledgment.principal_id must match authenticated principal",
            )
        if not _principal_may_launch_informed_autonomy(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="informed autonomy launches require tenant_owner or tenant_operator principal",
            )

        approved_by = f"autonomy:{principal_id}"
        approval_reason = f"User accepted disclaimer {entry.disclaimer_id}"
        requires_human_review = False
        autonomy_payload = {
            "schema_version": acknowledgment.schema_version,
            "disclaimer_id": acknowledgment.disclaimer_id,
            "disclaimer_text_hash": acknowledgment.disclaimer_text_hash,
            "accepted_at": acknowledgment.accepted_at,
            "principal_id": acknowledgment.principal_id,
            "action": acknowledgment.action,
            "side_effect_class": acknowledgment.side_effect_class,
        }
        return _LaunchAuthority(
            approved_by=approved_by,
            approval_reason=approval_reason,
            requires_human_review=requires_human_review,
            autonomy_acknowledgment=autonomy_payload,
        )

    if mode == "enforce" and action_tier(action_name) >= 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action {action_name} requires autonomy_acknowledgment when AJENDA_AUTONOMY_DISCLAIMER_MODE=enforce",
        )

    return _LaunchAuthority(
        approved_by=approved_by,
        approval_reason=approval_reason,
        requires_human_review=requires_human_review,
        autonomy_acknowledgment=None,
    )


def _validate_exposed_action(action_name: str) -> None:
    if action_name not in EXPOSED_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action {action_name!r} is not exposed by ability-runtime.",
        )


def _resolve_runtime_authority(
    *,
    db: Session,
    tenant_id: str,
    action_name: str,
    side_effect_class: SideEffectClass,
    capability_id: uuid.UUID | None,
    adapter_id: uuid.UUID | None,
) -> tuple[Capability | None, CapabilityAdapter | None]:
    if not _requires_runtime_authority(side_effect_class):
        return None, None
    if capability_id is None or adapter_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="runtime action requires pre-provisioned capability_id and adapter_id authority",
        )
    capability = CapabilityRepository(db).get_visible_for_tenant(
        capability_id=capability_id,
        tenant_id=tenant_id,
    )
    adapter = CapabilityAdapterRepository(db).get_visible_for_tenant(
        adapter_id=adapter_id,
        tenant_id=tenant_id,
    )
    if capability is None or adapter is None or not capability.enabled or not adapter.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="runtime authority is unavailable")
    if adapter.capability_id != capability.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="adapter does not belong to capability")
    action_names = {action_name, "tool.invoke"}
    if not action_names.intersection(capability.supported_task_types) or action_name not in capability.required_tools:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="capability does not authorize action")
    if not action_names.intersection(adapter.supported_task_types) or action_name not in adapter.required_tools:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="adapter does not authorize action")
    expected_class = _adapter_side_effect_classification(side_effect_class)
    if adapter.side_effect_classification != expected_class:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="adapter side-effect class mismatch")
    return capability, adapter


# Retained as a patch target for pre-authority contract fixtures. Production
# launch code calls the fail-closed resolver above directly.
def _ensure_runtime_authority(*args: Any, **kwargs: Any) -> tuple[Capability | None, CapabilityAdapter | None]:
    return _resolve_runtime_authority(*args, **kwargs)


def _build_task_metadata(
    *,
    action_name: str,
    input_payload: dict[str, Any],
    capability: Capability | None,
    adapter: CapabilityAdapter | None,
    request_body: AbilityTaskCreate,
    autonomy_acknowledgment: dict[str, Any] | None = None,
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

    if autonomy_acknowledgment is not None:
        execution_constraints: dict[str, Any] = {}
        execution_constraints["autonomy_acknowledgment"] = autonomy_acknowledgment
        metadata["execution_constraints"] = execution_constraints

    if request_body.credential_reference is not None:
        metadata["credential_reference"] = request_body.credential_reference.model_dump(mode="json")

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
