from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.ability_runtime import (
    AbilityTaskCreate,
    _resolve_launch_authority,
)
from backend.api.routes.ability_runtime import (
    router as ability_runtime_router,
)
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import MachinePrincipal, PrincipalType, UserPrincipal
from backend.services.autonomy.disclaimer_catalog import disclaimer_for_action


def _build_client(*, roles: tuple[str, ...] = ("tenant_owner",)) -> tuple[TestClient, uuid.UUID]:
    tenant_id = uuid.uuid4()
    app = FastAPI()
    principal = UserPrincipal(
        subject_id="human:owner@example.com",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.USER,
        roles=roles,
        permissions=frozenset(),
        email="owner@example.com",
    )

    @app.middleware("http")
    async def _inject_principal(request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = principal
        return await call_next(request)

    app.include_router(ability_runtime_router, prefix="/v1")

    def override_tenant_id() -> uuid.UUID:
        return tenant_id

    def override_db():
        session = MagicMock()
        yield session

    app.dependency_overrides[get_request_tenant_id] = override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = override_db
    app.dependency_overrides[get_queue_adapter] = lambda: MagicMock()
    return TestClient(app, raise_server_exceptions=False), tenant_id


def _tenant_owner_request(*, tenant_id: uuid.UUID) -> MagicMock:
    request = MagicMock()
    request.state.principal = UserPrincipal(
        subject_id="human:owner@example.com",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.USER,
        roles=("tenant_owner",),
        permissions=frozenset(),
        email="owner@example.com",
    )
    return request


@patch("backend.api.routes.ability_runtime.require_route_permission")
@patch("backend.api.routes.ability_runtime.QuotaEnforcementService")
@patch("backend.api.routes.ability_runtime.get_settings")
def test_enforce_mode_rejects_tier3_without_acknowledgment(
    mock_settings: MagicMock,
    mock_quota_cls: MagicMock,
    _mock_perm: MagicMock,
) -> None:
    settings = MagicMock()
    settings.autonomy_disclaimer_mode = "enforce"
    mock_settings.return_value = settings
    mock_quota_cls.return_value.check_tenant_active.return_value = None
    mock_quota_cls.return_value.require_feature.return_value = None
    client, _tenant_id = _build_client()

    response = client.post(
        "/v1/ability-runtime/tasks",
        json={
            "action": "gtm.crm_upsert",
            "input": {"record_type": "contact", "data": {"email": "a@example.com"}},
            "idempotency_key": "idem-1",
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
        },
    )
    assert response.status_code == 400
    assert "autonomy_acknowledgment" in response.json()["detail"]


@patch("backend.api.routes.ability_runtime.get_settings")
def test_pilot_mode_resolve_launch_authority_accepts_valid_acknowledgment(mock_settings: MagicMock) -> None:
    settings = MagicMock()
    settings.autonomy_disclaimer_mode = "pilot"
    mock_settings.return_value = settings

    entry = disclaimer_for_action("gtm.crm_upsert")
    assert entry is not None

    tenant_id = uuid.uuid4()
    body = AbilityTaskCreate(
        action="gtm.crm_upsert",
        input={"record_type": "contact", "data": {"email": "a@example.com"}},
        idempotency_key="idem-2",
        autonomy_acknowledgment={
            "schema_version": 1,
            "disclaimer_id": entry.disclaimer_id,
            "disclaimer_text_hash": entry.text_hash,
            "accepted_at": "2026-06-25T12:00:00Z",
            "principal_id": "human:owner@example.com",
            "action": "gtm.crm_upsert",
            "side_effect_class": "external_write",
        },
    )
    launch = _resolve_launch_authority(
        request=_tenant_owner_request(tenant_id=tenant_id),
        body=body,
        action_name="gtm.crm_upsert",
    )
    assert launch.approved_by == "autonomy:human:owner@example.com"
    assert launch.requires_human_review is False
    assert launch.autonomy_acknowledgment is not None


@patch("backend.api.routes.ability_runtime.get_settings")
def test_pilot_mode_resolve_launch_authority_accepts_tenant_operator(mock_settings: MagicMock) -> None:
    settings = MagicMock()
    settings.autonomy_disclaimer_mode = "pilot"
    mock_settings.return_value = settings

    entry = disclaimer_for_action("gtm.crm_upsert")
    assert entry is not None

    tenant_id = uuid.uuid4()
    request = MagicMock()
    request.state.principal = MachinePrincipal(
        subject_id="machine:operational-key",
        tenant_id=str(tenant_id),
        principal_type=PrincipalType.MACHINE,
        roles=("tenant_operator",),
        permissions=frozenset(),
        key_id="operational-key",
    )
    body = AbilityTaskCreate(
        action="gtm.crm_upsert",
        input={"record_type": "contact", "data": {"email": "a@example.com"}},
        idempotency_key="idem-operator",
        autonomy_acknowledgment={
            "schema_version": 1,
            "disclaimer_id": entry.disclaimer_id,
            "disclaimer_text_hash": entry.text_hash,
            "accepted_at": "2026-06-25T12:00:00Z",
            "principal_id": "machine:operational-key",
            "action": "gtm.crm_upsert",
            "side_effect_class": "external_write",
        },
    )
    launch = _resolve_launch_authority(request=request, body=body, action_name="gtm.crm_upsert")
    assert launch.approved_by == "autonomy:machine:operational-key"
    assert launch.requires_human_review is False
