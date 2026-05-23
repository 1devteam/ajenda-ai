from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
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
    app.dependency_overrides[get_queue_adapter] = lambda: MagicMock()
    return app


def _mission(*, tenant_id: uuid.UUID, mission_id: uuid.UUID) -> SimpleNamespace:
    now = SimpleNamespace(isoformat=lambda: "2026-05-23T00:00:00+00:00")
    return SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        objective="prove runtime boundary",
        status="running",
        metadata_json={"mission_intake": {"schema_version": 1}, "mission_plan": {"schema_version": 1}},
        created_at=now,
        updated_at=now,
    )


def _graph_payload() -> dict[str, object]:
    return {
        "graph_status": "approved",
        "nodes": [
            {
                "key": "collect-signals",
                "title": "Collect signals",
                "description": "Read approved CRM fields",
                "depends_on": [],
                "intended_task_type": "crm_research",
            }
        ],
        "edges": [],
        "metadata": {},
    }


def test_graph_creation_contract_persists_graph_without_queue_side_effects() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    repo = MagicMock()
    repo.get_for_tenant.return_value = _mission(tenant_id=tenant_id, mission_id=mission_id)
    repo.update_metadata.side_effect = lambda **kwargs: kwargs["mission"]

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
        patch("backend.api.routes.mission.get_queue_adapter") as queue_dep,
    ):
        response = client.post(f"/v1/missions/{mission_id}/task-graph", json=_graph_payload())

    assert response.status_code == 200
    task_repo_cls.assert_not_called()
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher_cls.assert_not_called()
    queue_dep.assert_not_called()


def test_runtime_task_materialization_contract_creates_planned_rows_without_enqueuing() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission = _mission(tenant_id=tenant_id, mission_id=mission_id)
    mission.metadata_json.update(
        {
            "mission_task_graph": {
                "schema_version": 2,
                "mission_id": str(mission_id),
                "graph_status": "approved",
                "graph_version": 1,
                "graph_fingerprint": "sha256:test",
                "nodes": [
                    {"key": "collect-signals", "node_key": "collect-signals", "intended_task_type": "crm_research"}
                ],
                "edges": [],
                "metadata": {},
            },
            "mission_graph_materialization": {
                "schema_version": 1,
                "materialization_status": "approved",
                "materialization_version": 1,
                "graph_reference": {
                    "graph_version": 1,
                    "graph_fingerprint": "sha256:test",
                    "node_count": 1,
                },
            },
            "runtime_admission": {
                "schema_version": 1,
                "admission_status": "admitted",
                "admission_version": 1,
                "graph_reference": {"graph_version": 1, "graph_fingerprint": "sha256:test", "node_count": 1},
                "materialization_reference": {
                    "metadata_key": "mission_graph_materialization",
                    "materialization_status": "approved",
                    "materialization_version": 1,
                    "graph_reference": {"graph_version": 1, "graph_fingerprint": "sha256:test", "node_count": 1},
                },
                "selected_nodes": [
                    {
                        "node_key": "collect-signals",
                        "runtime_task_type": "crm_research",
                        "capability_id": str(capability_id),
                    }
                ],
            },
        }
    )

    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    mission_repo.update_metadata.side_effect = lambda **kwargs: kwargs["mission"]

    task_repo = MagicMock()
    created_tasks = []

    def _add(task):
        task.id = uuid.uuid4()
        created_tasks.append(task)
        return task

    task_repo.add.side_effect = _add

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.CapabilityRepository") as capability_repo_cls,
        patch("backend.api.routes.mission.CapabilityAdapterRepository") as adapter_repo_cls,
        patch("backend.api.routes.mission.OutcomeReviewRepository") as outcome_repo_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
    ):
        capability_repo_cls.return_value.get_visible_for_tenant.return_value = SimpleNamespace(
            id=capability_id, name="crm_read", version="1.0.0"
        )
        capability_repo_cls.return_value.get_conflict_for_scope.return_value = SimpleNamespace(id=capability_id)
        adapter_repo_cls.return_value.get_visible_for_tenant.return_value = None
        outcome_repo_cls.return_value.list_for_mission.return_value = []
        response = client.post(f"/v1/missions/{mission_id}/runtime-task-materialization")

    assert response.status_code == 200
    assert created_tasks and all(task.status == "planned" for task in created_tasks)
    coordinator_cls.assert_not_called()
