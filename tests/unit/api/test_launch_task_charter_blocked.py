"""Charter enforcement at ability-runtime launch."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes.ability_runtime import AbilityTaskCreate, launch_task
from backend.services.operating_charter import OperatingCharter


class _AnyTenantId:
    def __eq__(self, _other: object) -> bool:
        return True

    def __ne__(self, _other: object) -> bool:
        return False


def _authorized_request(*, roles: tuple[str, ...] = ("guardian",)) -> MagicMock:
    request = MagicMock()
    request.state.principal = SimpleNamespace(
        subject_id="test-user",
        tenant_id=_AnyTenantId(),
        roles=roles,
        permissions=frozenset(),
    )
    return request


def _narrow_charter() -> OperatingCharter:
    return OperatingCharter(
        schema_version=1,
        may_prepare=("sales.qualify",),
        may_perform=(),
        never_do=("gtm.email_send",),
        approval_mode="none",
        escalation_email=None,
        escalation_phone=None,
        source="profile",
    )


def test_launch_task_rejects_charter_blocked_prepare_action() -> None:
    tenant_id = uuid.uuid4()
    db = MagicMock()
    queue = MagicMock()
    request = _authorized_request()
    body = AbilityTaskCreate(action="retrieval.hybrid_search", input={"query": "Ajenda", "limit": 3})

    profile = MagicMock()
    profile.approved_facts = {"operating_charter": {"value": _narrow_charter().to_fact_payload()}}
    quota_svc = MagicMock()

    with (
        patch("backend.api.routes.ability_runtime.BusinessProfileRepository") as profile_repo_cls,
        patch("backend.api.routes.ability_runtime.QuotaEnforcementService", return_value=quota_svc),
    ):
        profile_repo_cls.return_value.get_active_profile_for_tenant.return_value = profile
        with pytest.raises(HTTPException) as exc_info:
            launch_task(body=body, request=request, tenant_id=tenant_id, db=db, queue=queue)

    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "CHARTER_PREPARE_NOT_ALLOWED"
    quota_svc.check_and_record_mission_creation.assert_not_called()
