"""Unit tests for /v1/vertical-ops Phase B API routes."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import vertical_ops as vertical_ops_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import ExecutionTaskState
from backend.domain.mission import Mission
from backend.services.execution_coordinator import CoordinationResult
from backend.services.vertical_ops.template_service import (
    VerticalTemplateApplyResult,
    VerticalTemplateQueueResult,
)


def _build_app(tenant_id: uuid.UUID, *, roles: tuple[str, ...] = ("tenant_admin",)) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=roles,
        )
        return await call_next(request)

    app.include_router(vertical_ops_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    def _override_queue() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def test_list_templates_returns_phase_b_and_c_catalog() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch.object(vertical_ops_module, "require_route_permission"):
        response = client.get(
            "/v1/vertical-ops/templates",
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 200
    payload = response.json()
    ids = {item["template_id"] for item in payload["templates"]}
    assert {
        "vertical.research.v1",
        "vertical.email.v1",
        "vertical.social.v1",
        "vertical.ads.v1",
        "vertical.code.v1",
        "vertical.finance.v1",
    } <= ids
    assert all(item["grants_execution_authority"] is False for item in payload["templates"])
    phase_c = [item for item in payload["templates"] if item["phase"] == "C"]
    assert phase_c
    assert all(item["allows_runtime_queue"] is False for item in phase_c)


def test_phase_c_queue_rejected_by_api() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch.object(vertical_ops_module, "require_route_permission"):
        response = client.post(
            "/v1/vertical-ops/missions",
            json={"template_id": "vertical.ads.v1", "queue": True},
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 400
    assert "plan-only" in response.json()["detail"]


def test_get_unknown_template_404() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch.object(vertical_ops_module, "require_route_permission"):
        response = client.get(
            "/v1/vertical-ops/templates/vertical.does-not-exist.v1",
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 404


def test_create_mission_from_template_apply_only() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    applied = VerticalTemplateApplyResult(
        mission_id=mission_id,
        template_id="vertical.research.v1",
        created_task_ids=(task_id,),
        plan_contract={"schema_version": 1},
        task_graph={"schema_version": 1, "nodes": [], "edges": [], "metadata": {}, "graph_status": "draft"},
    )

    with (
        patch.object(vertical_ops_module, "require_route_permission"),
        patch.object(vertical_ops_module, "_enforce_quota_and_features"),
        patch.object(vertical_ops_module.VerticalOpsTemplateService, "build_bundle") as build_bundle,
        patch.object(vertical_ops_module.VerticalOpsTemplateService, "apply_to_mission", return_value=applied),
        patch.object(vertical_ops_module, "Mission", wraps=Mission),
    ):
        build_bundle.return_value = MagicMock(
            role_key="vertical.research",
            planned_tasks=(MagicMock(),),
            objective="Research competitors",
        )
        response = client.post(
            "/v1/vertical-ops/missions",
            json={"template_id": "vertical.research.v1", "queue": False},
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["mission_id"] == str(mission_id)
    assert body["template_id"] == "vertical.research.v1"
    assert body["queued"] is False
    assert body["grants_execution_authority"] is False
    assert body["created_task_ids"] == [str(task_id)]


def test_create_mission_with_queue_uses_apply_and_queue() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    applied = VerticalTemplateApplyResult(
        mission_id=mission_id,
        template_id="vertical.research.v1",
        created_task_ids=(task_id,),
        plan_contract={},
        task_graph={},
    )
    queued = VerticalTemplateQueueResult(
        results=(
            CoordinationResult(
                ok=True,
                task_id=task_id,
                state=ExecutionTaskState.QUEUED.value,
                reason=None,
            ),
        ),
        queued_task_ids=(task_id,),
        blocked_task_ids=(),
    )

    with (
        patch.object(vertical_ops_module, "require_route_permission"),
        patch.object(vertical_ops_module, "_enforce_quota_and_features"),
        patch.object(vertical_ops_module.VerticalOpsTemplateService, "build_bundle") as build_bundle,
        patch.object(
            vertical_ops_module.VerticalOpsTemplateService,
            "apply_and_queue",
            return_value=(applied, queued),
        ) as apply_and_queue,
    ):
        build_bundle.return_value = MagicMock(
            role_key="vertical.research",
            planned_tasks=(MagicMock(),),
            objective="Research competitors",
        )
        response = client.post(
            "/v1/vertical-ops/missions",
            json={"template_id": "vertical.research.v1", "queue": True},
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["queued"] is True
    assert body["queue_outcomes"][0]["ok"] is True
    assert body["queue_outcomes"][0]["state"] == "queued"
    apply_and_queue.assert_called_once()


def test_social_queue_requires_credential_reference() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=("tenant_admin",))
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch.object(vertical_ops_module, "require_route_permission"),
        patch.object(vertical_ops_module, "_enforce_quota_and_features"),
    ):
        response = client.post(
            "/v1/vertical-ops/missions",
            json={
                "template_id": "vertical.social.v1",
                "queue": True,
                "idempotency_keys": {"social-publish": "idem-1"},
            },
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 400
    assert "credential_references" in response.json()["detail"]


def test_queue_rejects_task_ids_outside_applied_template_set() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    allowed_task_id = uuid.uuid4()
    foreign_task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission = Mission(
        tenant_id=str(tenant_id),
        objective="research",
        status="planned",
        metadata_json={
            "vertical_ops_template": {
                "template_id": "vertical.research.v1",
                "allows_runtime_queue": True,
                "created_task_ids": [str(allowed_task_id)],
                "selected_step_keys": ["research-internal"],
            }
        },
    )
    mission.id = mission_id
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    with (
        patch.object(vertical_ops_module, "require_route_permission"),
        patch.object(vertical_ops_module, "MissionRepository", return_value=repo),
    ):
        response = client.post(
            f"/v1/vertical-ops/missions/{mission_id}/queue",
            json={"task_ids": [str(foreign_task_id)]},
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 400
    assert "created_task_ids" in response.json()["detail"]


def test_queue_accepts_subset_of_applied_template_task_ids() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task_a = uuid.uuid4()
    task_b = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission = Mission(
        tenant_id=str(tenant_id),
        objective="research",
        status="planned",
        metadata_json={
            "vertical_ops_template": {
                "template_id": "vertical.research.v1",
                "allows_runtime_queue": True,
                "created_task_ids": [str(task_a), str(task_b)],
                "selected_step_keys": ["research-internal"],
            }
        },
    )
    mission.id = mission_id
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    queued = VerticalTemplateQueueResult(
        results=(
            CoordinationResult(
                ok=True,
                task_id=task_a,
                state=ExecutionTaskState.QUEUED.value,
                reason=None,
            ),
        ),
        queued_task_ids=(task_a,),
        blocked_task_ids=(),
    )

    with (
        patch.object(vertical_ops_module, "require_route_permission"),
        patch.object(vertical_ops_module, "MissionRepository", return_value=repo),
        patch.object(
            vertical_ops_module.VerticalOpsTemplateService,
            "queue_planned_tasks",
            return_value=queued,
        ) as queue_planned,
    ):
        response = client.post(
            f"/v1/vertical-ops/missions/{mission_id}/queue",
            json={"task_ids": [str(task_a)]},
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["created_task_ids"] == [str(task_a)]
    assert body["queued"] is True
    queue_planned.assert_called_once()
    assert queue_planned.call_args.kwargs["task_ids"] == (task_a,)


def test_social_queue_requires_privileged_role() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=("member",))
    client = TestClient(app, raise_server_exceptions=False)

    with patch.object(vertical_ops_module, "require_route_permission"):
        response = client.post(
            "/v1/vertical-ops/missions",
            json={
                "template_id": "vertical.social.v1",
                "queue": True,
                "idempotency_keys": {"social-publish": "idem-1"},
                "credential_references": {
                    "social-publish": {
                        "credential_id": "cred-1",
                        "provider": "external_social",
                        "credential_type": "api_key",
                    }
                },
            },
            headers={"X-Tenant-Id": str(tenant_id)},
        )

    assert response.status_code == 403


def test_router_registers_vertical_ops_paths() -> None:
    from fastapi import FastAPI

    from backend.api.router import build_api_router

    app = FastAPI()
    app.include_router(build_api_router())
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/v1/vertical-ops/templates" in paths
    assert "/v1/vertical-ops/missions" in paths
    assert "/v1/vertical-ops/missions/{mission_id}/apply" in paths
    assert "/v1/vertical-ops/missions/{mission_id}/queue" in paths
