from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import capability_adapter as adapter_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(adapter_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _valid_payload(*, capability_id: uuid.UUID | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "crm-review-adapter",
        "version": "1.0.0",
        "capability_name": "crm-record-review",
        "capability_version": "1.0.0",
        "supported_task_types": ["crm.review", "crm.summarize"],
        "input_contract": {"required": ["account_id"]},
        "output_contract": {"properties": {"recommendation": {"type": "string"}}},
        "required_permissions": ["crm:read"],
        "required_tools": ["crm"],
        "execution_mode": "declarative",
        "risk_level": "medium",
        "approval_requirements": {
            "required": True,
            "approver_roles": ["operator"],
            "conditions": ["before outbound action"],
        },
        "evidence_expectations": ["record ids reviewed", "recommendation rationale"],
        "timeout_retry_hints": {"timeout_seconds": 30, "max_attempts": 2},
        "idempotency_expectations": {"idempotency_key_required": True},
        "side_effect_classification": "read_only",
        "enabled": True,
    }
    if capability_id is not None:
        payload["capability_id"] = str(capability_id)
    return payload


def _adapter_record(
    *, tenant_id: str | None, adapter_id: uuid.UUID | None = None, capability_id: uuid.UUID | None = None
) -> SimpleNamespace:
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    payload = _valid_payload(capability_id=capability_id)
    return SimpleNamespace(
        id=adapter_id or uuid.uuid4(),
        tenant_id=tenant_id,
        name=payload["name"],
        version=payload["version"],
        capability_id=capability_id,
        capability_name=payload["capability_name"],
        capability_version=payload["capability_version"],
        supported_task_types=payload["supported_task_types"],
        input_contract=payload["input_contract"],
        output_contract=payload["output_contract"],
        required_permissions=payload["required_permissions"],
        required_tools=payload["required_tools"],
        execution_mode=payload["execution_mode"],
        risk_level=payload["risk_level"],
        approval_requirements=payload["approval_requirements"],
        evidence_expectations=payload["evidence_expectations"],
        timeout_retry_hints=payload["timeout_retry_hints"],
        idempotency_expectations=payload["idempotency_expectations"],
        side_effect_classification=payload["side_effect_classification"],
        enabled=True,
        schema_version=1,
        created_at=now,
        updated_at=now,
    )


def _capability_record(
    *,
    tenant_id: str | None,
    capability_id: uuid.UUID | None = None,
    name: str = "crm-record-review",
    version: str = "1.0.0",
    supported_task_types: list[str] | None = None,
    risk_level: str = "medium",
    enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=capability_id or uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        version=version,
        supported_task_types=supported_task_types or ["crm.review", "crm.summarize"],
        risk_level=risk_level,
        enabled=enabled,
    )


def test_adapter_creation_persists_tenant_scoped_contract_without_runtime_queue_interaction() -> None:
    tenant_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    adapter_repo.add.return_value = _adapter_record(
        tenant_id=str(tenant_id), adapter_id=adapter_id, capability_id=capability_id
    )
    capability = _capability_record(tenant_id=str(tenant_id), capability_id=capability_id)
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = capability
    capability_repo.get_visible_by_name_version.return_value = capability

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload(capability_id=capability_id))

    assert response.status_code == 201
    body = response.json()
    assert body["adapter_id"] == str(adapter_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["scope"] == "tenant"
    assert body["capability_id"] == str(capability_id)
    assert body["supported_task_types"] == ["crm.review", "crm.summarize"]
    assert body["side_effect_classification"] == "read_only"
    adapter_repo.get_conflict_for_scope.assert_called_once_with(
        name="crm-review-adapter",
        version="1.0.0",
        tenant_id=str(tenant_id),
    )
    capability_repo.get_visible_for_tenant.assert_called_once_with(
        capability_id=capability_id, tenant_id=str(tenant_id)
    )
    capability_repo.get_visible_by_name_version.assert_not_called()
    created = adapter_repo.add.call_args.args[0]
    assert created.tenant_id == str(tenant_id)
    assert created.capability_id == capability_id
    assert created.required_tools == ["crm"]
    assert created.schema_version == 1
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    task_repo_cls.assert_not_called()


def test_adapter_validation_rejects_duplicate_task_types_before_persistence() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload["supported_task_types"] = ["crm.review", "crm.review"]
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository") as repo_cls:
        response = client.post("/v1/capability-adapters", json=payload)

    assert response.status_code == 422
    repo_cls.assert_not_called()


def test_adapter_create_requires_capability_binding() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload.pop("capability_name")
    payload.pop("capability_version")
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository") as repo_cls:
        response = client.post("/v1/capability-adapters", json=payload)

    assert response.status_code == 422
    assert "requires capability_id or capability_name/capability_version binding" in response.text
    repo_cls.assert_not_called()


def test_adapter_rejects_incomplete_capability_name_version_binding() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload.pop("capability_version")
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/v1/capability-adapters", json=payload)

    assert response.status_code == 422
    assert "requires both" in response.text


def test_adapter_create_honors_explicit_global_capability_id_when_tenant_has_same_name_version() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    adapter_repo.add.side_effect = lambda adapter: _adapter_record(
        tenant_id=adapter.tenant_id, adapter_id=uuid.uuid4(), capability_id=adapter.capability_id
    )
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = _capability_record(
        tenant_id=None, capability_id=capability_id
    )
    capability_repo.get_visible_by_name_version.return_value = _capability_record(tenant_id=str(tenant_id))

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload(capability_id=capability_id))

    assert response.status_code == 201
    assert response.json()["capability_id"] == str(capability_id)
    capability_repo.get_visible_for_tenant.assert_called_once_with(
        capability_id=capability_id, tenant_id=str(tenant_id)
    )
    capability_repo.get_visible_by_name_version.assert_not_called()
    assert adapter_repo.add.call_args.args[0].capability_id == capability_id


def test_adapter_create_rejects_name_version_mismatch_for_explicit_capability_id() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = _capability_record(
        tenant_id=None, capability_id=capability_id, name="global-review", version="2.0.0"
    )

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload(capability_id=capability_id))

    assert response.status_code == 422
    assert response.json() == {"detail": "capability_id does not match capability name/version binding"}
    capability_repo.get_visible_by_name_version.assert_not_called()
    adapter_repo.add.assert_not_called()


def test_adapter_create_rejects_cross_tenant_capability_reference() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = None

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload(capability_id=capability_id))

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced capability is not visible to tenant"}
    adapter_repo.add.assert_not_called()


def test_adapter_create_rejects_duplicate_name_version_scope() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = _adapter_record(tenant_id=str(tenant_id))

    with patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo):
        response = client.post("/v1/capability-adapters", json=_valid_payload())

    assert response.status_code == 409
    assert response.json() == {"detail": "capability adapter already exists for scope and version"}
    adapter_repo.add.assert_not_called()


def test_adapter_list_includes_tenant_and_global_visible_contracts() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    tenant_adapter = _adapter_record(tenant_id=str(tenant_id))
    global_adapter = _adapter_record(tenant_id=None)
    global_adapter.name = "shared-research-adapter"
    adapter_repo = MagicMock()
    adapter_repo.list_visible_for_tenant.return_value = [global_adapter, tenant_adapter]

    with patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo):
        response = client.get("/v1/capability-adapters")

    assert response.status_code == 200
    body = response.json()
    assert [item["scope"] for item in body["adapters"]] == ["global", "tenant"]
    assert [item["name"] for item in body["adapters"]] == ["shared-research-adapter", "crm-review-adapter"]
    adapter_repo.list_visible_for_tenant.assert_called_once_with(tenant_id=str(tenant_id))


def test_adapter_read_hides_cross_tenant_contract() -> None:
    tenant_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = None

    with patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo):
        response = client.get(f"/v1/capability-adapters/{adapter_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "capability adapter not found for tenant"}
    adapter_repo.get_visible_for_tenant.assert_called_once_with(adapter_id=adapter_id, tenant_id=str(tenant_id))


def test_adapter_update_persists_mutable_fields_for_tenant_owned_contract() -> None:
    tenant_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    adapter = _adapter_record(tenant_id=str(tenant_id), adapter_id=adapter_id)
    updated = _adapter_record(tenant_id=str(tenant_id), adapter_id=adapter_id)
    updated.enabled = False
    updated.execution_mode = "manual"
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = adapter
    adapter_repo.update.return_value = updated

    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(tenant_id=str(tenant_id))

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.patch(
            f"/v1/capability-adapters/{adapter_id}",
            json={"execution_mode": "manual", "enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["execution_mode"] == "manual"
    assert response.json()["enabled"] is False
    assert adapter.execution_mode == "manual"
    assert adapter.enabled is False
    adapter_repo.update.assert_called_once_with(adapter)


def test_adapter_patch_rejects_explicit_null_enabled() -> None:
    tenant_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/capability-adapters/{adapter_id}", json={"enabled": None})

    assert response.status_code == 422
    assert "cannot be null" in response.text


def test_adapter_create_resolves_visible_capability_by_name_version() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    adapter_repo.add.side_effect = lambda adapter: _adapter_record(
        tenant_id=adapter.tenant_id, adapter_id=uuid.uuid4(), capability_id=adapter.capability_id
    )
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(
        tenant_id=str(tenant_id), capability_id=capability_id
    )

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload())

    assert response.status_code == 201
    assert response.json()["capability_id"] == str(capability_id)
    capability_repo.get_visible_for_tenant.assert_not_called()
    capability_repo.get_visible_by_name_version.assert_called_once_with(
        name="crm-record-review", version="1.0.0", tenant_id=str(tenant_id)
    )
    assert adapter_repo.add.call_args.args[0].capability_id == capability_id


def test_adapter_create_fails_closed_when_name_version_capability_is_not_visible() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = None

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload())

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced capability name/version is not visible to tenant"}
    adapter_repo.add.assert_not_called()


def test_adapter_create_rejects_incompatible_supported_task_types() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(
        tenant_id=str(tenant_id), supported_task_types=["crm.review"]
    )

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload())

    assert response.status_code == 422
    assert "supported_task_types" in response.text
    adapter_repo.add.assert_not_called()


def test_adapter_create_rejects_understated_risk() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(
        tenant_id=str(tenant_id), risk_level="high"
    )

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload())

    assert response.status_code == 422
    assert "cannot understate" in response.text
    adapter_repo.add.assert_not_called()


def test_adapter_create_rejects_external_side_effect_without_approval() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_payload()
    payload["approval_requirements"] = {"required": False, "approver_roles": [], "conditions": []}
    payload["side_effect_classification"] = "external_side_effect"
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(tenant_id=str(tenant_id))

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=payload)

    assert response.status_code == 422
    assert "external_side_effect" in response.text
    adapter_repo.add.assert_not_called()


def test_adapter_create_rejects_enabled_adapter_for_disabled_capability() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_conflict_for_scope.return_value = None
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(
        tenant_id=str(tenant_id), enabled=False
    )

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post("/v1/capability-adapters", json=_valid_payload())

    assert response.status_code == 422
    assert "disabled capability" in response.text
    adapter_repo.add.assert_not_called()


def test_adapter_update_rejects_before_mutating_existing_record() -> None:
    tenant_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    adapter = _adapter_record(tenant_id=str(tenant_id), adapter_id=adapter_id)
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = adapter
    capability_repo = MagicMock()
    capability_repo.get_visible_by_name_version.return_value = _capability_record(
        tenant_id=str(tenant_id), supported_task_types=["crm.review"]
    )

    with (
        patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.capability_adapter.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.patch(
            f"/v1/capability-adapters/{adapter_id}",
            json={"supported_task_types": ["crm.review", "crm.email"], "enabled": False},
        )

    assert response.status_code == 422
    assert "supported_task_types" in response.text
    assert adapter.supported_task_types == ["crm.review", "crm.summarize"]
    assert adapter.enabled is True
    adapter_repo.update.assert_not_called()


def test_global_adapter_update_is_read_only_from_tenant_route() -> None:
    tenant_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = _adapter_record(tenant_id=None, adapter_id=adapter_id)

    with patch("backend.api.routes.capability_adapter.CapabilityAdapterRepository", return_value=adapter_repo):
        response = client.patch(f"/v1/capability-adapters/{adapter_id}", json={"enabled": False})

    assert response.status_code == 403
    assert response.json() == {"detail": "global capability adapters are read-only from tenant routes"}
    adapter_repo.update.assert_not_called()
