from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import capability as capability_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(capability_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _valid_payload() -> dict[str, object]:
    return {
        "name": "crm-record-review",
        "version": "1.0.0",
        "description": "Review CRM records and produce recommendations.",
        "supported_task_types": ["crm.review", "crm.summarize"],
        "input_schema_hints": {"required": ["account_id"]},
        "output_schema_hints": {"properties": {"recommendation": {"type": "string"}}},
        "required_permissions": ["crm:read"],
        "required_tools": ["crm"],
        "risk_level": "medium",
        "approval_requirements": {
            "required": True,
            "approver_roles": ["operator"],
            "conditions": ["before outbound action"],
        },
        "evidence_expectations": ["record ids reviewed", "recommendation rationale"],
        "execution_constraints": {"no_outbound_contact": True},
        "enabled": True,
    }


def _capability_record(*, tenant_id: str | None, capability_id: uuid.UUID | None = None) -> SimpleNamespace:
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    payload = _valid_payload()
    return SimpleNamespace(
        id=capability_id or uuid.uuid4(),
        tenant_id=tenant_id,
        name=payload["name"],
        version=payload["version"],
        description=payload["description"],
        supported_task_types=payload["supported_task_types"],
        input_schema_hints=payload["input_schema_hints"],
        output_schema_hints=payload["output_schema_hints"],
        required_permissions=payload["required_permissions"],
        required_tools=payload["required_tools"],
        risk_level=payload["risk_level"],
        approval_requirements=payload["approval_requirements"],
        evidence_expectations=payload["evidence_expectations"],
        execution_constraints=payload["execution_constraints"],
        enabled=True,
        schema_version=1,
        created_at=now,
        updated_at=now,
    )


def test_capability_creation_persists_tenant_scoped_contract_without_runtime_queue_interaction() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_conflict_for_scope.return_value = None
    repo.add.return_value = _capability_record(tenant_id=str(tenant_id), capability_id=capability_id)

    with (
        patch("backend.api.routes.capability.CapabilityRepository", return_value=repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
    ):
        response = client.post("/v1/capabilities", json=_valid_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["capability_id"] == str(capability_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["scope"] == "tenant"
    assert body["name"] == "crm-record-review"
    assert body["supported_task_types"] == ["crm.review", "crm.summarize"]
    assert body["approval_requirements"]["required"] is True
    repo.get_conflict_for_scope.assert_called_once_with(
        name="crm-record-review",
        version="1.0.0",
        tenant_id=str(tenant_id),
    )
    created = repo.add.call_args.args[0]
    assert created.tenant_id == str(tenant_id)
    assert created.required_tools == ["crm"]
    assert created.schema_version == 1
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    task_repo_cls.assert_not_called()


def test_capability_validation_rejects_duplicate_task_types_before_persistence() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload["supported_task_types"] = ["crm.review", "crm.review"]
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.routes.capability.CapabilityRepository") as repo_cls:
        response = client.post("/v1/capabilities", json=payload)

    assert response.status_code == 422
    repo_cls.assert_not_called()


def test_capability_create_rejects_duplicate_name_version_scope() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_conflict_for_scope.return_value = _capability_record(tenant_id=str(tenant_id))

    with patch("backend.api.routes.capability.CapabilityRepository", return_value=repo):
        response = client.post("/v1/capabilities", json=_valid_payload())

    assert response.status_code == 409
    assert response.json() == {"detail": "capability already exists for scope and version"}
    repo.add.assert_not_called()


def test_capability_list_includes_tenant_and_global_visible_contracts() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    tenant_capability = _capability_record(tenant_id=str(tenant_id))
    global_capability = _capability_record(tenant_id=None)
    global_capability.name = "shared-research"
    repo = MagicMock()
    repo.list_visible_for_tenant.return_value = [global_capability, tenant_capability]

    with patch("backend.api.routes.capability.CapabilityRepository", return_value=repo):
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert [item["scope"] for item in body["capabilities"]] == ["global", "tenant"]
    assert [item["name"] for item in body["capabilities"]] == ["shared-research", "crm-record-review"]
    repo.list_visible_for_tenant.assert_called_once_with(tenant_id=str(tenant_id))


def test_capability_read_hides_cross_tenant_contract() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_visible_for_tenant.return_value = None

    with patch("backend.api.routes.capability.CapabilityRepository", return_value=repo):
        response = client.get(f"/v1/capabilities/{capability_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "capability not found for tenant"}
    repo.get_visible_for_tenant.assert_called_once_with(capability_id=capability_id, tenant_id=str(tenant_id))


def test_capability_update_persists_mutable_fields_for_tenant_owned_contract() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    capability = _capability_record(tenant_id=str(tenant_id), capability_id=capability_id)
    updated = _capability_record(tenant_id=str(tenant_id), capability_id=capability_id)
    updated.description = "Updated contract."
    updated.enabled = False
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_visible_for_tenant.return_value = capability
    repo.update.return_value = updated

    with patch("backend.api.routes.capability.CapabilityRepository", return_value=repo):
        response = client.patch(
            f"/v1/capabilities/{capability_id}",
            json={"description": "Updated contract.", "enabled": False},
        )

    assert response.status_code == 200
    assert response.json()["description"] == "Updated contract."
    assert response.json()["enabled"] is False
    assert capability.description == "Updated contract."
    assert capability.enabled is False
    repo.update.assert_called_once_with(capability)


def test_capability_patch_rejects_explicit_null_enabled() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/capabilities/{capability_id}", json={"enabled": None})

    assert response.status_code == 422
    assert "cannot be null" in response.text


def test_capability_patch_rejects_explicit_null_description() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/capabilities/{capability_id}", json={"description": None})

    assert response.status_code == 422
    assert "cannot be null" in response.text


def test_global_capability_update_is_read_only_from_tenant_route() -> None:
    tenant_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_visible_for_tenant.return_value = _capability_record(tenant_id=None, capability_id=capability_id)

    with patch("backend.api.routes.capability.CapabilityRepository", return_value=repo):
        response = client.patch(f"/v1/capabilities/{capability_id}", json={"enabled": False})

    assert response.status_code == 403
    assert response.json() == {"detail": "global capabilities are read-only from tenant routes"}
    repo.update.assert_not_called()
