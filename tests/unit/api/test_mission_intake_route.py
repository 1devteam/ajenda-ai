from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.mission import (
    MISSION_GRAPH_MATERIALIZATION_METADATA_KEY,
    MISSION_INTAKE_METADATA_KEY,
    MISSION_PLAN_METADATA_KEY,
    MISSION_RUNTIME_ADMISSION_METADATA_KEY,
    MISSION_TASK_GRAPH_METADATA_KEY,
    build_mission_intake_metadata,
)
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(mission_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _valid_payload() -> dict[str, object]:
    return {
        "objective": "Recover qualified inbound opportunities that have not received follow-up.",
        "success_criteria": [
            {
                "description": "Every stale qualified opportunity has a recommended next action.",
                "evidence": ["opportunity review summary"],
            }
        ],
        "constraints": [
            {
                "name": "Do not contact customers",
                "description": "Research and prepare recommendations only; no outbound messages.",
                "hard": True,
            }
        ],
        "operator_notes": "Prioritize enterprise accounts first.",
        "context": {"source": "crm", "segment": "enterprise"},
        "priority": "high",
        "approval_required": True,
        "approval_expectations": ["operator approves recommendations before outreach"],
        "budget_limits": {"max_tasks": 5, "max_runtime_minutes": 30, "max_cost_usd": 25.5},
        "scope_limits": ["last 30 days only"],
        "allowed_actions": ["read_crm", "draft_recommendations"],
        "allowed_tools": ["crm", "analytics"],
        "compliance_category": "operational",
        "jurisdiction": "US-ALL",
    }


def _persisted_mission(*, tenant_id: uuid.UUID, mission_id: uuid.UUID, payload: dict[str, object]) -> SimpleNamespace:
    created_at = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        objective=payload["objective"],
        status="planned",
        compliance_category=payload["compliance_category"],
        jurisdiction=payload["jurisdiction"],
        metadata_json=build_mission_intake_metadata(
            success_criteria=payload["success_criteria"],
            constraints=payload["constraints"],
            operator_notes=payload["operator_notes"],
            context=payload["context"],
            priority=payload["priority"],
            approval_required=payload["approval_required"],
            approval_expectations=payload["approval_expectations"],
            budget_limits=payload["budget_limits"],
            scope_limits=payload["scope_limits"],
            allowed_actions=payload["allowed_actions"],
            allowed_tools=payload["allowed_tools"],
        ),
        created_at=created_at,
        updated_at=created_at,
    )


def test_mission_intake_creates_tenant_owned_mission_without_queueing_runtime_work() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    payload = _valid_payload()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    repo = MagicMock()
    repo.add.return_value = _persisted_mission(tenant_id=tenant_id, mission_id=mission_id, payload=payload)
    quota_svc = MagicMock()

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
    ):
        response = client.post("/v1/missions", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["mission_id"] == str(mission_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["objective"] == payload["objective"]
    assert body["status"] == "planned"
    assert body["compliance_category"] == "operational"
    assert body["jurisdiction"] == "US-ALL"
    assert body["intake"]["success_criteria"] == payload["success_criteria"]
    assert body["intake"]["constraints"] == payload["constraints"]
    assert body["intake"]["priority"] == "high"
    assert body["intake"]["approval_required"] is True
    assert body["intake"]["budget_limits"] == payload["budget_limits"]
    quota_svc.check_and_record_mission_creation.assert_called_once_with(tenant_id)
    created_mission = repo.add.call_args.args[0]
    assert created_mission.tenant_id == str(tenant_id)
    assert created_mission.metadata_json[MISSION_INTAKE_METADATA_KEY]["allowed_tools"] == ["crm", "analytics"]
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_mission_intake_rejects_missing_success_criteria() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload["success_criteria"] = []
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.post("/v1/missions", json=payload)

    assert response.status_code == 422
    repo_cls.assert_not_called()


def test_mission_intake_rejects_blank_constraint_fields() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload["constraints"] = [{"name": "   ", "description": "must be meaningful", "hard": True}]
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.post("/v1/missions", json=payload)

    assert response.status_code == 422
    repo_cls.assert_not_called()


def test_mission_intake_rejects_request_body_tenant_id() -> None:
    tenant_id = uuid.uuid4()
    payload = _valid_payload()
    payload["tenant_id"] = str(uuid.uuid4())
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.post("/v1/missions", json=payload)

    assert response.status_code == 422
    repo_cls.assert_not_called()


def test_mission_read_uses_tenant_scoped_repository_query_and_hides_foreign_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    repo = MagicMock()
    repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_mission_intake_route_requires_tenant_and_auth_under_middleware_stack() -> None:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks",
        oidc_issuer="https://example",
        oidc_audience="ajenda",
    )
    app.state.database_runtime = None
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.include_router(mission_module.router, prefix="/v1")
    client = TestClient(app, raise_server_exceptions=False)

    payload = {
        "objective": "Prepare a tenant-safe mission intake envelope.",
        "success_criteria": [{"description": "A mission record is created."}],
    }

    missing_tenant = client.post("/v1/missions", json=payload)
    assert missing_tenant.status_code == 400

    missing_auth = client.post(
        "/v1/missions",
        headers={"X-Tenant-Id": "3ac8e9a0-c351-41a5-95af-17dc9d7fd8c8"},
        json=payload,
    )
    assert missing_auth.status_code == 401


def _valid_plan_payload() -> dict[str, object]:
    return {
        "planning_status": "draft",
        "phases": [
            {
                "name": "Research",
                "objective": "Understand stale qualified opportunities.",
                "stages": [
                    {
                        "name": "Collect signals",
                        "intent": "Read approved CRM and analytics signals.",
                        "desired_outputs": ["signal summary"],
                        "capability_requirements": ["crm_read"],
                        "approval_required": False,
                    }
                ],
            }
        ],
        "planning_notes": "Prepare recommendations only; do not contact customers.",
        "desired_outputs": [
            {
                "name": "Opportunity follow-up plan",
                "description": "A recommendation set for stale qualified opportunities.",
                "acceptance_criteria": ["Every recommendation has supporting evidence."],
            }
        ],
        "capability_requirements": [
            {
                "name": "crm_read",
                "purpose": "Read CRM opportunities without writing outbound communications.",
                "required": True,
                "risk_level": "low",
            }
        ],
        "execution_strategy_hints": {"decomposition": "phase_first", "parallelism": "low"},
        "approval_gates": [
            {
                "name": "Operator review",
                "description": "Operator approves recommendations before customer contact.",
                "required_before": "customer_contact",
                "status": "required",
            }
        ],
        "operator_overrides": {"max_parallelism": 1},
        "estimated_scope": {"estimated_tasks": 3, "estimated_runtime_minutes": 20, "complexity": "medium"},
        "risk_annotations": [
            {
                "name": "Customer contact risk",
                "description": "This plan must not contact customers automatically.",
                "risk_level": "medium",
                "mitigation": "Approval gate before outreach.",
            }
        ],
    }


def _mission_with_metadata(
    *, tenant_id: uuid.UUID, mission_id: uuid.UUID, metadata_json: dict[str, object]
) -> SimpleNamespace:
    updated_at = datetime(2026, 5, 9, 12, 30, tzinfo=UTC)
    return SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        objective="Recover stale qualified opportunities.",
        status="planned",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json=metadata_json,
        created_at=updated_at,
        updated_at=updated_at,
    )


def test_mission_plan_upsert_persists_tenant_scoped_plan_without_queueing() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    plan_payload = _valid_plan_payload()
    intake_metadata = {MISSION_INTAKE_METADATA_KEY: {"schema_version": 1}}
    mission = _mission_with_metadata(tenant_id=tenant_id, mission_id=mission_id, metadata_json=intake_metadata)

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
    ):
        response = client.put(f"/v1/missions/{mission_id}/plan", json=plan_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mission_id"] == str(mission_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["plan"]["schema_version"] == 1
    assert body["plan"]["planning_status"] == "draft"
    assert body["plan"]["phases"] == plan_payload["phases"]
    assert body["plan"]["desired_outputs"] == plan_payload["desired_outputs"]
    assert body["plan"]["capability_requirements"] == plan_payload["capability_requirements"]
    assert body["plan"]["approval_gates"] == plan_payload["approval_gates"]
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    persisted_metadata = repo.update_metadata.call_args.kwargs["metadata_json"]
    assert persisted_metadata[MISSION_INTAKE_METADATA_KEY] == {"schema_version": 1}
    assert persisted_metadata["mission_plan"]["estimated_scope"] == plan_payload["estimated_scope"]
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_mission_plan_read_uses_tenant_scoped_repository_query() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    plan = {"schema_version": 1, "planning_status": "draft", "phases": []}
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={"mission_plan": plan},
    )
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/plan")

    assert response.status_code == 200
    assert response.json()["plan"] == plan
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_mission_plan_read_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/plan")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_mission_plan_validation_rejects_empty_phase_list_and_blank_stage_text() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    missing_phases = _valid_plan_payload()
    missing_phases["phases"] = []
    blank_stage = _valid_plan_payload()
    blank_stage["phases"] = [
        {
            "name": "Research",
            "objective": "Understand stale qualified opportunities.",
            "stages": [{"name": " ", "intent": "Collect signals."}],
        }
    ]

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        missing_phases_response = client.put(f"/v1/missions/{mission_id}/plan", json=missing_phases)
        blank_stage_response = client.put(f"/v1/missions/{mission_id}/plan", json=blank_stage)

    assert missing_phases_response.status_code == 422
    assert blank_stage_response.status_code == 422
    repo_cls.assert_not_called()


def test_mission_plan_upsert_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.put(f"/v1/missions/{mission_id}/plan", json=_valid_plan_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repo.update_metadata.assert_not_called()


def _valid_task_graph_payload() -> dict[str, object]:
    capability_id = str(uuid.uuid4())
    return {
        "graph_status": "draft",
        "nodes": [
            {
                "key": "collect-signals",
                "name": "Collect approved signals",
                "intended_task_type": "crm_research",
                "capability_references": [
                    {
                        "capability_id": capability_id,
                        "name": "crm_read",
                        "version": "1.0.0",
                        "purpose": "Read approved CRM opportunity records.",
                    }
                ],
                "input_contract": {"sources": ["crm"], "scope": "stale qualified opportunities"},
                "expected_output_contract": {"artifact": "signal_summary"},
                "risk_level": "low",
                "approval_required": False,
                "execution_constraints": {"read_only": True},
                "operator_notes": "Use tenant-approved CRM fields only.",
            },
            {
                "key": "draft-recommendations",
                "name": "Draft recommendations",
                "intended_task_type": "recommendation_draft",
                "capability_references": [{"name": "analysis", "purpose": "Prepare recommendations."}],
                "input_contract": {"requires": "signal_summary"},
                "expected_output_contract": {"artifact": "recommendation_set"},
                "risk_level": "medium",
                "approval_required": True,
                "execution_constraints": {"no_customer_contact": True},
                "operator_notes": "Do not queue or dispatch from this graph.",
            },
        ],
        "edges": [
            {
                "from_node_key": "collect-signals",
                "to_node_key": "draft-recommendations",
                "dependency_type": "depends_on",
                "description": "Recommendations require collected CRM signals.",
            }
        ],
        "operator_notes": "Contract only; future materialization will review this graph.",
    }


def test_mission_task_graph_upsert_persists_tenant_scoped_graph_without_queueing() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    graph_payload = _valid_task_graph_payload()
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={MISSION_INTAKE_METADATA_KEY: {"schema_version": 1}, "mission_plan": {"schema_version": 1}},
    )

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
    ):
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=graph_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mission_id"] == str(mission_id)
    assert body["tenant_id"] == str(tenant_id)
    task_graph = body["task_graph"]
    assert task_graph["schema_version"] == 1
    assert task_graph["mission_id"] == str(mission_id)
    assert task_graph["graph_status"] == "draft"
    assert task_graph["graph_version"] == 1
    assert task_graph["graph_fingerprint"].startswith("sha256:")
    assert task_graph["nodes"] == graph_payload["nodes"]
    assert task_graph["edges"] == graph_payload["edges"]
    assert task_graph["validation_metadata"]["validation_status"] == "valid"
    assert task_graph["validation_metadata"]["node_count"] == 2
    assert task_graph["validation_metadata"]["edge_count"] == 1
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    persisted_metadata = repo.update_metadata.call_args.kwargs["metadata_json"]
    assert persisted_metadata[MISSION_INTAKE_METADATA_KEY] == {"schema_version": 1}
    assert persisted_metadata["mission_plan"] == {"schema_version": 1}
    assert persisted_metadata["mission_task_graph"]["nodes"] == graph_payload["nodes"]
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_mission_task_graph_update_supersedes_existing_materialization_with_new_graph_identity() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_task_graph(tenant_id, mission_id)
    old_graph_fingerprint = mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY]["graph_fingerprint"]
    mission.metadata_json[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY] = {
        "schema_version": 1,
        "materialization_status": "approved",
        "materialization_version": 2,
        "graph_reference": {
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "graph_version": 7,
            "graph_fingerprint": old_graph_fingerprint,
        },
    }
    mission.metadata_json[MISSION_RUNTIME_ADMISSION_METADATA_KEY] = {
        "schema_version": 1,
        "admission_status": "admitted",
        "admission_version": 1,
        "graph_reference": {
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "graph_version": 7,
            "graph_fingerprint": old_graph_fingerprint,
        },
    }
    graph_payload = _valid_task_graph_payload()
    graph_payload["nodes"][0]["name"] = "Collect updated approved signals"

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
    ):
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=graph_payload)

    assert response.status_code == 200
    persisted_metadata = repo.update_metadata.call_args.kwargs["metadata_json"]
    task_graph = persisted_metadata[MISSION_TASK_GRAPH_METADATA_KEY]
    materialization = persisted_metadata[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY]
    admission = persisted_metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY]
    assert task_graph["graph_version"] == 8
    assert task_graph["graph_fingerprint"].startswith("sha256:")
    assert task_graph["graph_fingerprint"] != old_graph_fingerprint
    assert materialization["materialization_status"] == "superseded"
    assert materialization["superseded_reason"] == "task_graph_replaced"
    assert materialization["superseded_by_graph_version"] == 8
    assert materialization["superseded_by_graph_fingerprint"] == task_graph["graph_fingerprint"]
    assert admission["admission_status"] == "superseded"
    assert admission["superseded_reason"] == "task_graph_replaced"
    assert admission["superseded_by_graph_version"] == 8
    assert admission["superseded_by_graph_fingerprint"] == task_graph["graph_fingerprint"]
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_mission_task_graph_read_uses_tenant_scoped_repository_query() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    task_graph = {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "graph_status": "draft",
        "nodes": _valid_task_graph_payload()["nodes"],
        "edges": [],
        "operator_notes": None,
        "validation_metadata": {"validation_status": "valid"},
    }
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={"mission_task_graph": task_graph},
    )
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/task-graph")

    assert response.status_code == 200
    assert response.json()["task_graph"] == task_graph
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_mission_task_graph_read_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/task-graph")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_mission_task_graph_upsert_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=_valid_task_graph_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    repo.update_metadata.assert_not_called()


def test_mission_task_graph_validation_rejects_duplicate_node_keys() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_task_graph_payload()
    payload["nodes"][1]["key"] = "collect-signals"

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=payload)

    assert response.status_code == 422
    assert "task graph node keys must be unique" in response.text
    repo_cls.assert_not_called()


def test_mission_task_graph_validation_rejects_edge_to_missing_node() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_task_graph_payload()
    payload["edges"][0]["to_node_key"] = "missing-node"

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=payload)

    assert response.status_code == 422
    assert "task graph edges must reference existing node keys" in response.text
    repo_cls.assert_not_called()


def test_mission_task_graph_validation_rejects_cycle() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_task_graph_payload()
    payload["edges"].append(
        {
            "from_node_key": "draft-recommendations",
            "to_node_key": "collect-signals",
            "dependency_type": "depends_on",
        }
    )

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=payload)

    assert response.status_code == 422
    assert "task graph must be acyclic" in response.text
    repo_cls.assert_not_called()


def test_mission_task_graph_validation_rejects_empty_node_list() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_task_graph_payload()
    payload["nodes"] = []
    payload["edges"] = []

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.put(f"/v1/missions/{mission_id}/task-graph", json=payload)

    assert response.status_code == 422
    repo_cls.assert_not_called()


def _valid_materialization_payload(capability_id: str | None = None) -> dict[str, object]:
    selection: dict[str, object] = {
        "node_key": "collect-signals",
        "capability_name": "crm_read",
        "capability_version": "1.0.0",
        "selection_reason": "Matches the read-only CRM research node contract.",
        "selected_by": "planner-contract-test",
        "alternatives_considered": ["manual_export"],
    }
    if capability_id is not None:
        selection["capability_id"] = capability_id
    return {
        "materialization_status": "validated",
        "materialization_source": "mission_plan",
        "materialization_source_version": "1",
        "planner_provenance": {
            "planner_type": "contract_planner",
            "planner_id": "planner-v1",
            "planning_run_id": "run-123",
            "plan_schema_version": 1,
            "inputs_checksum": "sha256:test-input",
        },
        "capability_selection_provenance": [selection],
        "graph_validation_result": {
            "validation_status": "valid",
            "summary": "Graph shape and capability selections passed contract validation.",
            "validated_at": "2026-05-09T12:00:00Z",
            "checks": [
                {"name": "node_keys", "status": "passed", "details": "All selected nodes exist."},
                {"name": "capabilities", "status": "passed", "details": "Referenced capabilities are visible."},
            ],
        },
        "operator_review": {
            "status": "pending",
            "notes": "Operator has not approved runtime execution.",
        },
        "graph_generation_metadata": {
            "generator": "contract-compiler",
            "generation_mode": "deterministic",
            "generated_at": "2026-05-09T12:00:00Z",
            "compiler_version": "1.0.0",
            "source_plan_version": "1",
            "deterministic_inputs": {"plan_key": "mission_plan", "graph_key": "mission_task_graph"},
        },
        "deterministic_compilation_metadata": {
            "compiler_name": "planner-to-graph-contract-compiler",
            "compiler_version": "1.0.0",
            "compilation_boundary": "planner_contract_to_task_graph_contract",
            "input_fingerprint": "sha256:input",
            "output_fingerprint": "sha256:output",
            "deterministic": True,
        },
        "generation_notes": ["Metadata-only materialization; no runtime queueing."],
    }


def _mission_with_task_graph(tenant_id: uuid.UUID, mission_id: uuid.UUID) -> SimpleNamespace:
    graph_payload = _valid_task_graph_payload()
    task_graph = {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "graph_status": "approved",
        "graph_version": 7,
        "graph_fingerprint": "sha256:existing-graph",
        "nodes": graph_payload["nodes"],
        "edges": graph_payload["edges"],
        "operator_notes": graph_payload["operator_notes"],
        "validation_metadata": {"validation_status": "valid"},
    }
    return _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={
            MISSION_INTAKE_METADATA_KEY: {"schema_version": 1},
            "mission_plan": {"schema_version": 1, "planning_status": "approved"},
            MISSION_TASK_GRAPH_METADATA_KEY: task_graph,
        },
    )


def test_graph_materialization_persists_metadata_without_queueing_or_runtime_calls() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_task_graph(tenant_id, mission_id)
    original_graph = mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY]

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission, metadata_json):
        mission.metadata_json = metadata_json
        return mission

    mission_repo.update_metadata.side_effect = _update_metadata
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(id=capability_id)

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
    ):
        response = client.post(
            f"/v1/missions/{mission_id}/materialize-graph",
            json=_valid_materialization_payload(str(capability_id)),
        )

    assert response.status_code == 200
    body = response.json()
    materialization = body["materialization"]
    assert materialization["schema_version"] == 1
    assert materialization["mission_id"] == str(mission_id)
    assert materialization["materialization_status"] == "validated"
    assert materialization["materialization_version"] == 1
    assert materialization["planner_provenance"]["planner_type"] == "contract_planner"
    assert materialization["capability_selection_provenance"][0]["capability_id"] == str(capability_id)
    assert materialization["graph_validation_result"]["validation_status"] == "valid"
    assert materialization["operator_review"]["status"] == "pending"
    assert materialization["deterministic_compilation_metadata"]["deterministic"] is True
    assert materialization["graph_reference"]["node_count"] == 2
    assert materialization["graph_reference"]["graph_version"] == 7
    assert materialization["graph_reference"]["graph_fingerprint"] == "sha256:existing-graph"
    persisted_metadata = mission_repo.update_metadata.call_args.kwargs["metadata_json"]
    assert persisted_metadata[MISSION_TASK_GRAPH_METADATA_KEY] == original_graph
    assert MISSION_GRAPH_MATERIALIZATION_METADATA_KEY in persisted_metadata
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    capability_repo.get_visible_for_tenant.assert_called_once_with(
        capability_id=capability_id, tenant_id=str(tenant_id)
    )
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_graph_materialization_read_uses_tenant_scoped_repository_query() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    materialization = {"schema_version": 1, "materialization_status": "validated"}
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: materialization},
    )
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/materialization")

    assert response.status_code == 200
    assert response.json()["materialization"] == materialization
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_graph_materialization_read_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    repo = MagicMock()
    repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.get(f"/v1/missions/{mission_id}/materialization")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_graph_materialization_update_increments_version_and_preserves_existing_graph() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_task_graph(tenant_id, mission_id)
    mission.metadata_json[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY] = {
        "schema_version": 1,
        "materialization_version": 3,
        "materialized_at": "2026-05-09T11:00:00+00:00",
    }
    original_graph = mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY]
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission, metadata_json):
        mission.metadata_json = metadata_json
        return mission

    repo.update_metadata.side_effect = _update_metadata

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.CapabilityRepository") as capability_repo_cls,
    ):
        response = client.post(
            f"/v1/missions/{mission_id}/materialize-graph",
            json=_valid_materialization_payload(),
        )

    assert response.status_code == 200
    materialization = response.json()["materialization"]
    assert materialization["materialization_version"] == 4
    assert materialization["materialized_at"] == "2026-05-09T11:00:00+00:00"
    assert repo.update_metadata.call_args.kwargs["metadata_json"][MISSION_TASK_GRAPH_METADATA_KEY] == original_graph
    capability_repo_cls.return_value.get_visible_for_tenant.assert_not_called()


def test_graph_materialization_rejects_missing_task_graph() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={MISSION_INTAKE_METADATA_KEY: {"schema_version": 1}},
    )
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=repo):
        response = client.post(
            f"/v1/missions/{mission_id}/materialize-graph",
            json=_valid_materialization_payload(),
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "mission task graph is required before materialization"}
    repo.update_metadata.assert_not_called()


def test_graph_materialization_rejects_missing_capability_id() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_task_graph(tenant_id, mission_id)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.CapabilityRepository", return_value=capability_repo),
    ):
        response = client.post(
            f"/v1/missions/{mission_id}/materialize-graph",
            json=_valid_materialization_payload(str(capability_id)),
        )

    assert response.status_code == 400
    assert response.json() == {"detail": f"capability not found for tenant: {capability_id}"}
    mission_repo.update_metadata.assert_not_called()


def test_graph_materialization_validation_requires_structured_validation_summary() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_materialization_payload()
    payload["graph_validation_result"] = {"validation_status": "valid", "summary": " "}

    with patch("backend.api.routes.mission.MissionRepository") as repo_cls:
        response = client.post(f"/v1/missions/{mission_id}/materialize-graph", json=payload)

    assert response.status_code == 422
    assert "graph validation summary is required" in response.text
    repo_cls.assert_not_called()


def test_mission_lifecycle_returns_contract_metadata_and_related_summaries_without_runtime_side_effects() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    timestamp = datetime(2026, 5, 9, 13, 0, tzinfo=UTC)
    metadata = {
        MISSION_INTAKE_METADATA_KEY: {"schema_version": 1, "priority": "high"},
        MISSION_PLAN_METADATA_KEY: {"schema_version": 1, "planning_status": "approved"},
        MISSION_TASK_GRAPH_METADATA_KEY: {
            "schema_version": 1,
            "graph_status": "approved",
            "graph_version": 2,
            "nodes": [{"key": "collect-signals"}],
            "edges": [],
        },
        MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: {
            "schema_version": 1,
            "materialization_status": "validated",
            "materialization_version": 1,
        },
        MISSION_RUNTIME_ADMISSION_METADATA_KEY: {
            "schema_version": 1,
            "admission_status": "admitted",
            "execution_task_records": [],
        },
    }
    mission = _mission_with_metadata(tenant_id=tenant_id, mission_id=mission_id, metadata_json=metadata)
    evidence = SimpleNamespace(
        id=uuid.uuid4(),
        evidence_type="artifact",
        evidence_source="contract-test",
        collection_status="collected",
        confidence=0.91,
        created_at=timestamp,
        updated_at=timestamp,
    )
    review = SimpleNamespace(
        id=uuid.uuid4(),
        review_status="completed",
        review_decision="approved",
        reviewer_type="human",
        confidence=0.86,
        created_at=timestamp,
        updated_at=timestamp,
    )
    retrieval = SimpleNamespace(
        id=uuid.uuid4(),
        retrieval_strategy="keyword",
        retrieval_status="completed",
        confidence=0.77,
        created_at=timestamp,
        updated_at=timestamp,
    )
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    evidence_repo = MagicMock()
    evidence_repo.list_for_mission.return_value = [evidence]
    outcome_repo = MagicMock()
    outcome_repo.list_for_mission.return_value = [review]
    retrieval_repo = MagicMock()
    retrieval_repo.list_for_mission.return_value = [retrieval]

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository", return_value=outcome_repo),
        patch("backend.api.routes.mission.RetrievalContractRepository", return_value=retrieval_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.QuotaEnforcementService") as quota_cls,
    ):
        response = client.get(f"/v1/missions/{mission_id}/lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["mission"]["mission_id"] == str(mission_id)
    assert body["mission"]["tenant_id"] == str(tenant_id)
    assert body["mission"]["status"] == "planned"
    assert body["intake"] == metadata[MISSION_INTAKE_METADATA_KEY]
    assert body["plan"] == metadata[MISSION_PLAN_METADATA_KEY]
    assert body["task_graph"] == metadata[MISSION_TASK_GRAPH_METADATA_KEY]
    assert body["materialization"] == metadata[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY]
    assert body["runtime_admission"] == metadata[MISSION_RUNTIME_ADMISSION_METADATA_KEY]
    assert body["evidence"]["count"] == 1
    assert body["evidence"]["records"][0]["evidence_id"] == str(evidence.id)
    assert body["outcome_reviews"]["count"] == 1
    assert body["outcome_reviews"]["records"][0]["review_id"] == str(review.id)
    assert body["memory_promotions"] == {"count": 0, "records": []}
    assert body["retrieval_contracts"]["count"] == 1
    assert body["retrieval_contracts"]["records"][0]["retrieval_id"] == str(retrieval.id)
    assert body["completeness"] == {
        "has_intake": True,
        "has_plan": True,
        "has_task_graph": True,
        "has_materialization": True,
        "has_runtime_admission": True,
        "has_evidence": True,
        "has_outcome_review": True,
        "has_memory_promotions": False,
        "has_retrieval_contracts": True,
    }
    assert body["missing_next_steps"] == ["review_memory_promotion"]
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    evidence_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    outcome_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    retrieval_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    mission_repo.add.assert_not_called()
    mission_repo.update_metadata.assert_not_called()
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()
    quota_cls.assert_not_called()


def test_mission_lifecycle_reports_missing_next_steps_when_layers_are_absent() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={MISSION_INTAKE_METADATA_KEY: {"schema_version": 1}},
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
    body = response.json()
    assert body["completeness"] == {
        "has_intake": True,
        "has_plan": False,
        "has_task_graph": False,
        "has_materialization": False,
        "has_runtime_admission": False,
        "has_evidence": False,
        "has_outcome_review": False,
        "has_memory_promotions": False,
        "has_retrieval_contracts": False,
    }
    assert body["missing_next_steps"] == [
        "create_mission_plan",
        "create_task_graph",
        "materialize_task_graph",
        "admit_graph_to_runtime",
        "attach_evidence",
        "create_outcome_review",
        "review_memory_promotion",
        "create_retrieval_contract",
    ]
    assert body["plan"] is None
    assert body["task_graph"] is None
    assert body["materialization"] is None
    assert body["runtime_admission"] is None
    assert body["evidence"] == {"count": 0, "records": []}
    assert body["outcome_reviews"] == {"count": 0, "records": []}
    assert body["retrieval_contracts"] == {"count": 0, "records": []}


def test_mission_lifecycle_treats_superseded_runtime_admission_as_incomplete() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={
            MISSION_INTAKE_METADATA_KEY: {"schema_version": 1},
            MISSION_PLAN_METADATA_KEY: {"schema_version": 1},
            MISSION_TASK_GRAPH_METADATA_KEY: {"schema_version": 1},
            MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: {
                "schema_version": 1,
                "materialization_status": "approved",
            },
            MISSION_RUNTIME_ADMISSION_METADATA_KEY: {
                "schema_version": 1,
                "admission_status": "superseded",
            },
        },
    )
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    evidence_repo = MagicMock()
    evidence_repo.list_for_mission.return_value = []
    outcome_repo = MagicMock()
    outcome_repo.list_for_mission.return_value = []
    retrieval_repo = MagicMock()
    retrieval_repo.list_for_mission.return_value = []

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository", return_value=outcome_repo),
        patch("backend.api.routes.mission.RetrievalContractRepository", return_value=retrieval_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
    ):
        response = client.get(f"/v1/missions/{mission_id}/lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_admission"]["admission_status"] == "superseded"
    assert body["completeness"]["has_runtime_admission"] is False
    assert "admit_graph_to_runtime" in body["missing_next_steps"]
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_mission_lifecycle_treats_non_admitted_runtime_status_as_incomplete() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={
            MISSION_INTAKE_METADATA_KEY: {"schema_version": 1},
            MISSION_PLAN_METADATA_KEY: {"schema_version": 1},
            MISSION_TASK_GRAPH_METADATA_KEY: {"schema_version": 1},
            MISSION_GRAPH_MATERIALIZATION_METADATA_KEY: {
                "schema_version": 1,
                "materialization_status": "approved",
            },
            MISSION_RUNTIME_ADMISSION_METADATA_KEY: {
                "schema_version": 1,
                "admission_status": "validated",
            },
        },
    )
    repo = MagicMock()
    repo.get_for_tenant.return_value = mission
    evidence_repo = MagicMock()
    evidence_repo.list_for_mission.return_value = []
    outcome_repo = MagicMock()
    outcome_repo.list_for_mission.return_value = []
    retrieval_repo = MagicMock()
    retrieval_repo.list_for_mission.return_value = []

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=repo),
        patch("backend.api.routes.mission.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository", return_value=outcome_repo),
        patch("backend.api.routes.mission.RetrievalContractRepository", return_value=retrieval_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
    ):
        response = client.get(f"/v1/missions/{mission_id}/lifecycle")

    assert response.status_code == 200
    body = response.json()
    assert body["runtime_admission"]["admission_status"] == "validated"
    assert body["completeness"]["has_runtime_admission"] is False
    assert "admit_graph_to_runtime" in body["missing_next_steps"]
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_mission_lifecycle_hides_cross_tenant_mission_without_loading_related_layers() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.EvidenceRepository") as evidence_repo_cls,
        patch("backend.api.routes.mission.OutcomeReviewRepository") as outcome_repo_cls,
        patch("backend.api.routes.mission.RetrievalContractRepository") as retrieval_repo_cls,
    ):
        response = client.get(f"/v1/missions/{mission_id}/lifecycle")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    evidence_repo_cls.assert_not_called()
    outcome_repo_cls.assert_not_called()
    retrieval_repo_cls.assert_not_called()


def _mission_with_runtime_admission_layers(
    *, tenant_id: uuid.UUID, mission_id: uuid.UUID, materialization_status: str = "validated"
) -> SimpleNamespace:
    mission = _mission_with_task_graph(tenant_id, mission_id)
    task_graph = mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY]
    mission.metadata_json[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY] = {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "materialization_status": materialization_status,
        "materialization_version": 1,
        "capability_selection_provenance": [
            {
                "node_key": "collect-signals",
                "capability_name": "crm_read",
                "selection_reason": "Matches node contract.",
            }
        ],
        "graph_reference": {
            "metadata_key": MISSION_TASK_GRAPH_METADATA_KEY,
            "schema_version": 1,
            "graph_status": task_graph["graph_status"],
            "graph_version": task_graph["graph_version"],
            "graph_fingerprint": task_graph["graph_fingerprint"],
            "node_count": len(task_graph["nodes"]),
            "edge_count": len(task_graph["edges"]),
        },
    }
    return mission


def _valid_runtime_admission_payload(
    *, node_key: str = "collect-signals", capability_id: uuid.UUID | None = None, adapter_id: uuid.UUID | None = None
) -> dict[str, object]:
    selected_node: dict[str, object] = {
        "node_key": node_key,
        "runtime_task_type": "crm_research",
        "operator_notes": "Admission only; do not queue.",
    }
    if capability_id is not None:
        selected_node["capability_id"] = str(capability_id)
    if adapter_id is not None:
        selected_node["adapter_id"] = str(adapter_id)
    return {
        "admission_status": "validated",
        "admitted_by": "operator@example.com",
        "selected_nodes": [selected_node],
        "validation_notes": ["Adapter execution remains future work."],
    }


def test_runtime_admission_persists_metadata_without_queueing_or_runtime_calls() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_runtime_admission_layers(tenant_id=tenant_id, mission_id=mission_id)
    mission.metadata_json[MISSION_INTAKE_METADATA_KEY]["preserved"] = True
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission, metadata_json):
        mission.metadata_json = metadata_json
        return mission

    mission_repo.update_metadata.side_effect = _update_metadata
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(id=capability_id)
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(id=adapter_id)
    outcome_repo = MagicMock()
    outcome_repo.list_for_mission.return_value = []

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.mission.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository", return_value=outcome_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
    ):
        response = client.post(
            f"/v1/missions/{mission_id}/runtime-admission",
            json=_valid_runtime_admission_payload(capability_id=capability_id, adapter_id=adapter_id),
        )

    assert response.status_code == 200
    admission = response.json()["runtime_admission"]
    assert admission["schema_version"] == 1
    assert admission["mission_id"] == str(mission_id)
    assert admission["admission_status"] == "validated"
    assert admission["graph_reference"]["graph_version"] == 7
    assert admission["graph_reference"]["graph_fingerprint"] == "sha256:existing-graph"
    assert admission["materialization_reference"]["materialization_version"] == 1
    assert admission["selected_nodes"][0]["node_key"] == "collect-signals"
    assert admission["selected_nodes"][0]["runtime_task_type"] == "crm_research"
    assert admission["selected_nodes"][0]["capability_id"] == str(capability_id)
    assert admission["selected_nodes"][0]["adapter_id"] == str(adapter_id)
    assert admission["execution_task_records"] == []
    assert admission["runtime_authority"] == {
        "creates_execution_tasks": False,
        "enqueues_work": False,
        "dispatches_workers": False,
        "requires_explicit_queue_admission_for_execution": True,
    }
    persisted_metadata = mission_repo.update_metadata.call_args.kwargs["metadata_json"]
    assert persisted_metadata[MISSION_INTAKE_METADATA_KEY]["preserved"] is True
    assert persisted_metadata[MISSION_TASK_GRAPH_METADATA_KEY] == mission.metadata_json[MISSION_TASK_GRAPH_METADATA_KEY]
    assert persisted_metadata[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY]["materialization_status"] == "validated"
    capability_repo.get_visible_for_tenant.assert_called_once_with(
        capability_id=capability_id, tenant_id=str(tenant_id)
    )
    adapter_repo.get_visible_for_tenant.assert_called_once_with(adapter_id=adapter_id, tenant_id=str(tenant_id))
    outcome_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()


def test_runtime_admission_read_uses_tenant_scoped_repository_query() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    runtime_admission = {"schema_version": 1, "admission_status": "validated"}
    mission = _mission_with_metadata(
        tenant_id=tenant_id,
        mission_id=mission_id,
        metadata_json={MISSION_RUNTIME_ADMISSION_METADATA_KEY: runtime_admission},
    )
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.get(f"/v1/missions/{mission_id}/runtime-admission")

    assert response.status_code == 200
    assert response.json()["runtime_admission"] == runtime_admission
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_runtime_admission_is_tenant_scoped() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.CapabilityRepository") as capability_repo_cls,
        patch("backend.api.routes.mission.CapabilityAdapterRepository") as adapter_repo_cls,
        patch("backend.api.routes.mission.OutcomeReviewRepository") as outcome_repo_cls,
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    mission_repo.update_metadata.assert_not_called()
    capability_repo_cls.assert_not_called()
    adapter_repo_cls.assert_not_called()
    outcome_repo_cls.assert_not_called()


def test_runtime_admission_rejects_missing_task_graph() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_metadata(tenant_id=tenant_id, mission_id=mission_id, metadata_json={})
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 400
    assert response.json() == {"detail": "mission task graph is required before runtime admission"}
    mission_repo.update_metadata.assert_not_called()


def test_runtime_admission_rejects_missing_materialization() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_task_graph(tenant_id, mission_id)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 400
    assert response.json() == {"detail": "mission graph materialization is required before runtime admission"}
    mission_repo.update_metadata.assert_not_called()


def test_runtime_admission_rejects_superseded_materialization() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_runtime_admission_layers(
        tenant_id=tenant_id, mission_id=mission_id, materialization_status="superseded"
    )
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 400
    assert response.json() == {"detail": "superseded graph materialization cannot be admitted"}
    mission_repo.update_metadata.assert_not_called()


def test_runtime_admission_rejects_materialization_graph_fingerprint_mismatch() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_runtime_admission_layers(tenant_id=tenant_id, mission_id=mission_id)
    mission.metadata_json[MISSION_GRAPH_MATERIALIZATION_METADATA_KEY]["graph_reference"]["graph_fingerprint"] = (
        "sha256:stale"
    )
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 400
    assert response.json() == {"detail": "materialization graph reference does not match current task graph"}
    mission_repo.update_metadata.assert_not_called()


def test_runtime_admission_rejects_missing_selected_node() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_runtime_admission_layers(tenant_id=tenant_id, mission_id=mission_id)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository") as outcome_repo_cls,
    ):
        outcome_repo_cls.return_value.list_for_mission.return_value = []
        response = client.post(
            f"/v1/missions/{mission_id}/runtime-admission",
            json=_valid_runtime_admission_payload(node_key="missing-node"),
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "runtime admission references missing node: missing-node"}
    mission_repo.update_metadata.assert_not_called()


def test_runtime_admission_rejects_duplicate_selected_nodes() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _valid_runtime_admission_payload()
    payload["selected_nodes"] = [payload["selected_nodes"][0], dict(payload["selected_nodes"][0])]

    with patch("backend.api.routes.mission.MissionRepository") as mission_repo_cls:
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=payload)

    assert response.status_code == 422
    assert "runtime admission selected node keys must be unique" in response.text
    mission_repo_cls.assert_not_called()


def test_runtime_admission_rejects_rejected_outcome_review() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_runtime_admission_layers(tenant_id=tenant_id, mission_id=mission_id)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    outcome_repo = MagicMock()
    outcome_repo.list_for_mission.return_value = [SimpleNamespace(review_status="approved", review_decision="rejected")]

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository", return_value=outcome_repo),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 400
    assert response.json() == {"detail": "rejected outcome review blocks runtime admission"}
    mission_repo.update_metadata.assert_not_called()


def test_runtime_admission_does_not_create_execution_task_rows() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission_with_runtime_admission_layers(tenant_id=tenant_id, mission_id=mission_id)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission, metadata_json):
        mission.metadata_json = metadata_json
        return mission

    mission_repo.update_metadata.side_effect = _update_metadata

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.OutcomeReviewRepository") as outcome_repo_cls,
        patch("backend.api.routes.mission.CapabilityRepository") as capability_repo_cls,
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
    ):
        outcome_repo_cls.return_value.list_for_mission.return_value = []
        capability_repo_cls.return_value.get_visible_for_tenant.return_value = SimpleNamespace(id=uuid.uuid4())
        response = client.post(f"/v1/missions/{mission_id}/runtime-admission", json=_valid_runtime_admission_payload())

    assert response.status_code == 200
    assert response.json()["runtime_admission"]["execution_task_records"] == []
    task_repo_cls.assert_not_called()
