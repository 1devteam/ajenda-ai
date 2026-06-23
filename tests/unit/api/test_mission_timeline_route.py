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
    foreign_tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    created_at = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    updated_at = datetime(2026, 5, 25, 12, 10, tzinfo=UTC)

    mission = SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        status="planned",
        created_at=created_at,
        updated_at=updated_at,
        metadata_json={
            "mission_plan": {
                "planning_status": "draft",
                "updated_at": datetime(2026, 5, 25, 12, 5, tzinfo=UTC).isoformat(),
            },
            "runtime_admission": {
                "admission_status": "admitted",
                "updated_at": datetime(2026, 5, 25, 12, 8, tzinfo=UTC).isoformat(),
            },
        },
    )
    tenant_task = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=str(tenant_id),
        status="planned",
        created_at=datetime(2026, 5, 25, 12, 6, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, 12, 9, tzinfo=UTC),
    )
    foreign_task = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=str(foreign_tenant_id),
        status="planned",
        created_at=datetime(2026, 5, 25, 12, 7, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, 12, 7, tzinfo=UTC),
    )

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [tenant_task, foreign_task]

    plan_repo = MagicMock()
    plan_repo.get_for_mission.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["authority_class"] == "read_model"
    assert body["side_effect_class"] == "none"
    assert body["does_not_execute_runtime_work"] is True

    timestamps = [datetime.fromisoformat(event["timestamp"]) for event in body["events"]]
    assert timestamps == sorted(timestamps)

    included_task_ids = {
        event["details"]["task_id"]
        for event in body["events"]
        if event["source"] == "execution_task" and "task_id" in event["details"]
    }
    assert str(tenant_task.id) in included_task_ids
    assert str(foreign_task.id) not in included_task_ids


def test_mission_timeline_endpoint_fallbacks_invalid_metadata_updated_at_without_500() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_updated_at = datetime(2026, 5, 25, 14, 0, tzinfo=UTC)

    mission = SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        status="planned",
        created_at=datetime(2026, 5, 25, 13, 0, tzinfo=UTC),
        updated_at=mission_updated_at,
        metadata_json={
            "mission_plan": {"planning_status": "draft", "updated_at": "not-an-iso-date"},
            "runtime_admission": {"admission_status": "admitted", "updated_at": 12345},
        },
    )

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = []

    plan_repo = MagicMock()
    plan_repo.get_for_mission.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/timeline")

    assert response.status_code == 200
    body = response.json()
    fallback_events = [event for event in body["events"] if event["source"] == "mission_metadata"]
    assert fallback_events
    for event in fallback_events:
        assert event["timestamp"] == mission_updated_at.isoformat()


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


def test_mission_timeline_endpoint_handles_mixed_naive_and_aware_timestamps() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission = SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        status="planned",
        created_at=datetime(2026, 5, 25, 11, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, 11, 30, tzinfo=UTC),
        metadata_json={
            "mission_plan": {"planning_status": "draft", "updated_at": "2026-05-25T11:05:00"},
            "runtime_admission": {"admission_status": "admitted", "updated_at": "2026-05-25T11:10:00+00:00"},
        },
    )
    task = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=str(tenant_id),
        status="planned",
        created_at=datetime(2026, 5, 25, 11, 15, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, 11, 20, tzinfo=UTC),
    )

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [task]

    plan_repo = MagicMock()
    plan_repo.get_for_mission.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/timeline")

    assert response.status_code == 200
    body = response.json()

    def _normalized(ts: str) -> datetime:
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    timestamps = [_normalized(event["timestamp"]) for event in body["events"]]
    assert timestamps == sorted(timestamps)
