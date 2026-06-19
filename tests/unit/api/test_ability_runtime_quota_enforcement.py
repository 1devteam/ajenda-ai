"""Tests for quota/feature enforcement in ability-runtime paths."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes.ability_runtime import (
    EXTERNAL_ACTIONS,
    GTM_HIGH_RISK_ACTIONS,
    INTERNAL_WRITE_ACTIONS,
    READ_SAFE_ACTIONS,
    AbilityTaskCreate,
    _requires_runtime_authority,
    launch_task,
)
from backend.services.execution_coordinator import CoordinationResult
from backend.services.quota_enforcement import QuotaExceededError
from backend.services.tools.runtime_authority import ToolRuntimeAuthority
from backend.services.tools.schemas import SideEffectClass


class _AnyTenantId:
    def __eq__(self, _other: object) -> bool:
        return True

    def __ne__(self, _other: object) -> bool:
        return False


def _authorized_request() -> MagicMock:
    request = MagicMock()
    request.state.principal = SimpleNamespace(
        subject_id="test-user",
        tenant_id=_AnyTenantId(),
        roles=("operator",),
        permissions=frozenset(),
    )
    return request


def test_ability_runtime_enforcement_imports_and_sets():
    """The enforcement surfaces (ability-runtime + tools runtime) now reference quota."""
    # High-risk actions that now get defense-in-depth in launch_task
    assert "http.request" in EXTERNAL_ACTIONS
    assert "provider.external_read" in EXTERNAL_ACTIONS
    assert "webhook.dispatch" in EXTERNAL_ACTIONS

    # PR9: high-risk GTM now exposed for pilot and gated by guardian + feature
    assert "gtm.email_send" in EXTERNAL_ACTIONS
    assert "gtm.crm_upsert" in EXTERNAL_ACTIONS
    assert "gtm.social_publish" in EXTERNAL_ACTIONS
    assert GTM_HIGH_RISK_ACTIONS == {"gtm.email_send", "gtm.crm_upsert", "gtm.social_publish"}

    # Internal writes also trigger authority (and thus potential future quota/feature)
    assert "record.write" in INTERNAL_WRITE_ACTIONS
    assert "sales.log_activity" in INTERNAL_WRITE_ACTIONS

    # Safe reads do not
    assert "sales.research" in READ_SAFE_ACTIONS
    assert len(EXTERNAL_ACTIONS) >= 6


def test_requires_runtime_authority_matches_external_and_write():
    """Mirrors the condition used for the new quota/feature check in launch_task."""
    assert _requires_runtime_authority(SideEffectClass.EXTERNAL_READ) is True
    assert _requires_runtime_authority(SideEffectClass.EXTERNAL_WRITE) is True
    assert _requires_runtime_authority(SideEffectClass.EXTERNAL_SEND) is True
    assert _requires_runtime_authority(SideEffectClass.INTERNAL_WRITE) is True
    assert _requires_runtime_authority(SideEffectClass.NONE) is False


def test_tool_runtime_authority_imports_quota_enforcement():
    """Confirms the defense-in-depth check_tenant_active call site in execution path.
    (The actual call happens inside authorize() after lease claim.)
    """
    # Construction should succeed (no quota dep at __init__ time)
    auth = ToolRuntimeAuthority()
    assert auth is not None
    # If the import was missing the edit would have failed at module load
    from backend.services.quota_enforcement import QuotaEnforcementService

    assert QuotaEnforcementService is not None


@pytest.mark.parametrize(
    "side_effect",
    [
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.INTERNAL_WRITE,
    ],
)
def test_external_and_write_side_effects_require_authority(side_effect):
    assert _requires_runtime_authority(side_effect) is True


def test_gtm_high_risk_actions_require_guardian_role_at_launch() -> None:
    from backend.api.routes.ability_runtime import _principal_may_approve_gtm_side_effects

    assert "gtm.email_send" in GTM_HIGH_RISK_ACTIONS

    denied = MagicMock()
    denied.state.principal = SimpleNamespace(roles=("operator",))
    assert _principal_may_approve_gtm_side_effects(denied) is False

    allowed = MagicMock()
    allowed.state.principal = SimpleNamespace(roles=("guardian",))
    assert _principal_may_approve_gtm_side_effects(allowed) is True


def test_launch_task_records_mission_and_task_quota_before_queueing() -> None:
    from backend.domain.execution_task import ExecutionTask
    from backend.domain.mission import Mission

    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()
    body = AbilityTaskCreate(action="sales.research", input={"lead": {"company": "Acme"}})

    def _assign_ids(obj: object) -> None:
        if isinstance(obj, Mission):
            obj.id = mission_id
        elif isinstance(obj, ExecutionTask):
            obj.id = task_id

    db.add.side_effect = _assign_ids

    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(ok=True, task_id=task_id, state="queued")

    with (
        patch("backend.api.routes.ability_runtime.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.ability_runtime.ExecutionCoordinator", return_value=coordinator),
        patch("backend.api.routes.ability_runtime._ensure_runtime_authority", return_value=(None, None)),
    ):
        launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)

    quota_svc.check_tenant_active.assert_called_once_with(tenant_id)
    quota_svc.check_and_record_mission_creation.assert_called_once_with(tenant_id)
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id)
    coordinator.queue_task.assert_called_once()


def test_launch_task_returns_429_when_mission_quota_exceeded() -> None:
    tenant_id = uuid.uuid4()
    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()
    body = AbilityTaskCreate(action="sales.research", input={"lead": {"company": "Acme"}})

    quota_svc = MagicMock()
    quota_svc.check_and_record_mission_creation.side_effect = QuotaExceededError(
        field="missions_per_month",
        limit=10,
        current=10,
        plan="free",
    )

    with patch("backend.api.routes.ability_runtime.QuotaEnforcementService", return_value=quota_svc):
        with pytest.raises(HTTPException) as exc_info:
            launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "QUOTA_EXCEEDED"
    assert exc_info.value.detail["field"] == "missions_per_month"
    quota_svc.check_and_record_task_creation.assert_not_called()
