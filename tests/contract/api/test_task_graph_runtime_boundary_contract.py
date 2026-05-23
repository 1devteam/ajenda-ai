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
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={"mission_intake": {"schema_version": 1}, "mission_plan": {"schema_version": 1}},
        created_at=now,
        updated_at=now,
    )


def _graph_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "graph_status": "draft",
        "nodes": [
            {
                "node_key": "collect-signals",
                "key": "collect-signals",
                "title": "Collect signals",
                "description": "Read approved CRM fields.",
                "capability_reference": {
                    "capability_id": None,
                    "name": "crm_read",
                    "version": "1.0.0",
                    "purpose": "Read records.",
                },
                "capability_references": [
                    {
                        "capability_id": None,
                        "name": "crm_read",
                        "version": "1.0.0",
                        "purpose": "Read records.",
                    }
                ],
                "input_contract": {"sources": ["crm"]},
                "output_contract": {"artifact": "signal_summary"},
                "metadata": {"read_only": True},
            }
        ],
        "edges": [],
        "metadata": {},
    }


def _persist_metadata(*, mission: SimpleNamespace, metadata_json: dict[str, object]) -> SimpleNamespace:
    mission.metadata_json = metadata_json
    return mission


def test_graph_creation_contract_persists_graph_without_queue_side_effects() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    repo = MagicMock()
    repo.get_for_tenant.return_value = _mission(tenant_id=tenant_id, mission_id=mission_id)
    repo.update_metadata.side_effect = _persist_metadata

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
        patch("backend.api.routes.mission.get_queue_adapter") as queue_dep,
    ):
        response = client.post(f"/v1/missions/{mission_id}/task-graph", json=_graph_payload())

    assert response.status_code == 200, response.text
    task_repo_cls.assert_not_called()
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher_cls.assert_not_called()
    queue_dep.assert_not_called()


def test_runtime_task_materialization_contract_creates_planned_rows_without_enqueuing() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission = _mission(tenant_id=tenant_id, mission_id=mission_id)
    mission.metadata_json.update(
        {
            "mission_task_graph": _graph_payload(),
            "graph_materialization": {"schema_version": 1, "materialization_status": "approved"},
            "runtime_admission": {"schema_version": 1, "admission_status": "admitted"},
        }
    )

    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    mission_repo.get_for_tenant.return_value = mission
    mission_repo.update_metadata.side_effect = _persist_metadata

    task_repo = MagicMock()
    created_tasks = []

    def _add(task):
        task.id = uuid.uuid4()
        created_tasks.append(task)
        return task

    task_repo.add.side_effect = _add

    readiness = mission_module.RuntimeReadinessRead(
        mission_id=mission_id,
        tenant_id=str(tenant_id),
        ready=True,
        readiness_status="ready",
        checked_at="2026-05-23T00:00:00+00:00",
        graph_reference=mission.metadata_json["mission_task_graph"],
        materialization_reference=mission.metadata_json["graph_materialization"],
        admission_reference=mission.metadata_json["runtime_admission"],
        selected_node_count=1,
        checks=[],
        blockers=[],
        warnings=[],
    )
    preview_item = mission_module.RuntimeTaskPreviewItem(
        preview_task_key="collect-signals",
        graph_node_key="collect-signals",
        graph_node_name="Collect signals",
        runtime_task_type="echo",
        payload_preview=mission_module.RuntimeTaskPreviewPayload(
            mission_id=mission_id,
            graph_node_key="collect-signals",
            graph_version=1,
            graph_fingerprint="sha256:test",
            materialization_version=1,
            admission_version=1,
            runtime_task_type="echo",
            input_contract={"input": {"message": "hello"}},
            expected_output_contract={"artifact": "signal_summary"},
            execution_constraints={},
        ),
        capability_reference=None,
        adapter_reference=None,
        materialization_selection_reference=None,
        dependency_keys=[],
        operator_notes=None,
    )

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission._build_mission_runtime_readiness", return_value=readiness),
        patch("backend.api.routes.mission._build_runtime_task_preview_items", return_value=[preview_item]),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-task-materialization")

    assert response.status_code == 200, response.text
    assert created_tasks and all(task.status == "planned" for task in created_tasks)
    coordinator_cls.assert_not_called()
