from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(mission_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    return app


def test_mission_timeline_endpoint_returns_read_only_tenant_scoped_events() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    mission = SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        status="planned",
        created_at=now,
        updated_at=now,
        metadata_json={"mission_plan": {"planning_status": "draft", "updated_at": now.isoformat()}},
    )
    task = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=str(tenant_id),
        status="planned",
        created_at=now,
        updated_at=now,
    )

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [task]

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["authority_class"] == "read_model"
    assert body["does_not_execute_runtime_work"] is True
    assert len(body["events"]) >= 3
    assert any(event["event_type"] == "mission_plan_recorded" for event in body["events"])


def test_mission_timeline_endpoint_fails_closed_for_missing_or_foreign_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
    ):
        response = client.get(f"/v1/missions/{mission_id}/timeline")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    task_repo_cls.assert_not_called()
