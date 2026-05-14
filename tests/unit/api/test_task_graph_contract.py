from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.mission import MISSION_PLAN_METADATA_KEY, MISSION_TASK_GRAPH_METADATA_KEY


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(mission_module.router, prefix="/v1")

    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    return app


def _mission(
    *, tenant_id: uuid.UUID, mission_id: uuid.UUID, metadata_json: dict[str, object] | None = None
) -> SimpleNamespace:
    now = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        objective="Recover stale opportunities.",
        status="planned",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json=metadata_json or {MISSION_PLAN_METADATA_KEY: {"schema_version": 1}},
        created_at=now,
        updated_at=now,
    )


def _valid_graph_payload() -> dict[str, object]:
    return {
        "nodes": [
            {
                "node_key": "collect-signals",
                "title": "Collect signals",
                "description": "Read approved CRM fields.",
                "capability_reference": "crm_read",
                "input_contract": {"source": "crm"},
                "output_contract": {"artifact": "signal_summary"},
                "metadata": {"read_only": True},
            },
            {
                "node_key": "draft-recommendations",
                "title": "Draft recommendations",
                "description": "Prepare recommendations.",
                "capability_reference": {"name": "analysis"},
                "input_contract": {"requires": "signal_summary"},
                "output_contract": {"artifact": "recommendation_set"},
                "metadata": {"approval_required": True},
            },
        ],
        "edges": [{"from_node_key": "collect-signals", "to_node_key": "draft-recommendations", "metadata": {}}],
    }


def test_valid_graph_is_accepted_persisted_and_read_without_runtime_interaction() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id)
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission, metadata_json):
        mission.metadata_json = metadata_json
        return mission

    repo.update_metadata.side_effect = _update_metadata

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        post_response = client.post(f"/v1/missions/{mission_id}/task-graph", json=_valid_graph_payload())
        get_response = client.get(f"/v1/missions/{mission_id}/task-graph")

    assert post_response.status_code == 200
    assert get_response.status_code == 200
    assert post_response.json()["task_graph"] == get_response.json()["task_graph"]
    persisted = repo.update_metadata.call_args.kwargs["metadata_json"]
    assert persisted[MISSION_TASK_GRAPH_METADATA_KEY]["nodes"][0]["node_key"] == "collect-signals"
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()
    dispatcher_cls.assert_not_called()


def test_invalid_graph_payloads_fail_before_repository_access() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    duplicate = _valid_graph_payload()
    duplicate["nodes"][1]["node_key"] = "collect-signals"  # type: ignore[index]
    missing = _valid_graph_payload()
    missing["edges"][0]["to_node_key"] = "missing"  # type: ignore[index]
    self_dependency = _valid_graph_payload()
    self_dependency["edges"][0]["to_node_key"] = "collect-signals"  # type: ignore[index]
    cycle = _valid_graph_payload()
    cycle["edges"].append({"from_node_key": "draft-recommendations", "to_node_key": "collect-signals"})  # type: ignore[union-attr]
    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        responses = [
            client.post(f"/v1/missions/{mission_id}/task-graph", json=payload)
            for payload in (duplicate, missing, self_dependency, cycle)
        ]

    assert [response.status_code for response in responses] == [422, 422, 422, 422]
    assert "unique" in responses[0].text
    assert "existing node_keys" in responses[1].text
    assert "self-depend" in responses[2].text
    assert "acyclic" in responses[3].text
    repo_cls.assert_not_called()


def test_get_missing_task_graph_fails_explicitly() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_for_tenant.return_value = _mission(tenant_id=tenant_id, mission_id=mission_id)

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/task-graph")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission task graph not found"}


def test_lifecycle_reflects_task_graph_presence_and_removes_missing_next_step() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)
    graph = mission_module.build_mission_task_graph_contract_metadata(
        nodes=_valid_graph_payload()["nodes"],
        edges=_valid_graph_payload()["edges"],  # type: ignore[arg-type]
    )
    mission = _mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={MISSION_PLAN_METADATA_KEY: {"schema_version": 1}, MISSION_TASK_GRAPH_METADATA_KEY: graph},
    )
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.EvidenceRepository") as evidence_repo_cls,
        patch("backend.api.routes.mission.OutcomeReviewRepository") as outcome_repo_cls,
        patch("backend.api.routes.mission.RetrievalContractRepository") as retrieval_repo_cls,
    ):
        evidence_repo_cls.return_value.list_for_mission.return_value = []
        outcome_repo_cls.return_value.list_for_mission.return_value = []
        retrieval_repo_cls.return_value.list_for_mission.return_value = []
        response = client.get(f"/v1/missions/{mission_id}/lifecycle")

    assert response.status_code == 200
    lifecycle = response.json()
    assert lifecycle["completeness"]["has_task_graph"] is True
    assert "create_task_graph" not in lifecycle["missing_next_steps"]
    assert lifecycle["task_graph"] == graph
