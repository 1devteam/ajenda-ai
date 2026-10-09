import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.api.routes.ability_runtime_contracts import AbilityTaskCreate
from backend.api.routes.ability_runtime_policy import (
    GTM_HIGH_RISK_ACTIONS,
    _adapter_side_effect_classification,
    _requires_runtime_authority,
)
from backend.app.config import get_settings
from backend.domain.capability import Capability
from backend.domain.capability_adapter import CapabilityAdapter
from backend.repositories.capability_adapter_repository import CapabilityAdapterRepository
from backend.repositories.capability_repository import CapabilityRepository
from backend.services.abilities.role_contracts import RoleName
from backend.services.autonomy.disclaimer_catalog import (
    AutonomyPolicyError,
    action_tier,
    parse_autonomy_acknowledgment,
    validate_autonomy_acknowledgment,
)
from backend.services.tools.schemas import SideEffectClass


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

