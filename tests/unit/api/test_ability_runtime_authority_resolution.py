from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes.ability_runtime import _resolve_runtime_authority
from backend.services.tools.schemas import SideEffectClass


def _authority_records(*, tenant_id: str, action: str, classification: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    capability_id = uuid.uuid4()
    capability = SimpleNamespace(
        id=capability_id,
        tenant_id=tenant_id,
        enabled=True,
        supported_task_types=["tool.invoke", action],
        required_tools=[action],
    )
    adapter = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        enabled=True,
        capability_id=capability_id,
        supported_task_types=["tool.invoke", action],
        required_tools=[action],
        side_effect_classification=classification,
    )
    return capability, adapter


def test_runtime_launch_cannot_self_issue_missing_authority() -> None:
    with pytest.raises(HTTPException, match="pre-provisioned") as exc_info:
        _resolve_runtime_authority(
            db=MagicMock(),
            tenant_id="tenant-a",
            action_name="gtm.email_send",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            capability_id=None,
            adapter_id=None,
        )
    assert exc_info.value.status_code == 409


def test_runtime_launch_rejects_authority_not_visible_to_tenant() -> None:
    with (
        patch(
            "backend.api.routes.ability_runtime_authority.CapabilityRepository.get_visible_for_tenant",
            return_value=None,
        ),
        patch(
            "backend.api.routes.ability_runtime_authority.CapabilityAdapterRepository.get_visible_for_tenant",
            return_value=None,
        ),
        pytest.raises(HTTPException, match="unavailable") as exc_info,
    ):
        _resolve_runtime_authority(
            db=MagicMock(),
            tenant_id="tenant-a",
            action_name="gtm.email_send",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            capability_id=uuid.uuid4(),
            adapter_id=uuid.uuid4(),
        )
    assert exc_info.value.status_code == 409


def test_runtime_launch_uses_preprovisioned_exact_authority_without_writes() -> None:
    capability, adapter = _authority_records(
        tenant_id="tenant-a",
        action="gtm.email_send",
        classification=SideEffectClass.EXTERNAL_SEND.value,
    )
    session = MagicMock()
    with (
        patch(
            "backend.api.routes.ability_runtime_authority.CapabilityRepository.get_visible_for_tenant",
            return_value=capability,
        ) as capability_get,
        patch(
            "backend.api.routes.ability_runtime_authority.CapabilityAdapterRepository.get_visible_for_tenant",
            return_value=adapter,
        ) as adapter_get,
    ):
        resolved = _resolve_runtime_authority(
            db=session,
            tenant_id="tenant-a",
            action_name="gtm.email_send",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            capability_id=capability.id,
            adapter_id=adapter.id,
        )

    assert resolved == (capability, adapter)
    capability_get.assert_called_once_with(capability_id=capability.id, tenant_id="tenant-a")
    adapter_get.assert_called_once_with(adapter_id=adapter.id, tenant_id="tenant-a")
    session.add.assert_not_called()
    session.flush.assert_not_called()
