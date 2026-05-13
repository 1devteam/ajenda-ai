from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.mission import MissionPlan, build_mission_plan_contract_metadata


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


def _mission(*, tenant_id: uuid.UUID, mission_id: uuid.UUID) -> SimpleNamespace:
    now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        objective="Recover stale opportunities.",
        status="planned",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={"mission_intake": {"schema_version": 1}},
        created_at=now,
        updated_at=now,
    )


def _plan(*, tenant_id: uuid.UUID, mission_id: uuid.UUID, plan_id: uuid.UUID | None = None) -> MissionPlan:
    now = datetime(2026, 5, 13, 12, 30, tzinfo=UTC)
    plan = MissionPlan(
        id=plan_id or uuid.uuid4(),
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        status="draft",
        metadata_json=build_mission_plan_contract_metadata(
            objectives=["Recover stale opportunities."],
            constraints=["No customer contact."],
            assumptions=["CRM data is current."],
            acceptance_criteria=["Recommendations include rationale."],
            planned_steps=[
                {
                    "sequence": 1,
                    "title": "Collect signals",
                    "description": "Read approved CRM fields.",
                    "depends_on": [],
                    "expected_output": "Signal summary",
                    "metadata": {"source": "crm"},
                }
            ],
            risk_notes=["Outbound contact requires later approval."],
        ),
    )
    plan.created_at = now
    plan.updated_at = now
    return plan


def _payload() -> dict[str, object]:
    return {
        "status": "draft",
        "objectives": ["Recover stale opportunities."],
        "constraints": ["No customer contact."],
        "assumptions": ["CRM data is current."],
        "acceptance_criteria": ["Recommendations include rationale."],
        "planned_steps": [
            {
                "sequence": 1,
                "title": "Collect signals",
                "description": "Read approved CRM fields.",
                "depends_on": [],
                "expected_output": "Signal summary",
                "metadata": {"source": "crm"},
            }
        ],
        "risk_notes": ["Outbound contact requires later approval."],
    }


def test_tenant_can_create_mission_plan_without_runtime_side_effects() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = _mission(tenant_id=tenant_id, mission_id=mission_id)
    plan_repo = MagicMock()
    plan_repo.create_or_get_active_for_mission.return_value = _plan(tenant_id=tenant_id, mission_id=mission_id)

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository") as task_repo_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        response = client.post(f"/v1/missions/{mission_id}/plan", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["mission_id"] == str(mission_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["status"] == "draft"
    assert body["metadata"]["schema_version"] == 1
    assert body["metadata"]["planned_steps"][0]["sequence"] == 1
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    plan_repo.create_or_get_active_for_mission.assert_called_once()
    task_repo_cls.assert_not_called()
    executor_cls.assert_not_called()
    coordinator_cls.assert_not_called()
    dispatcher_cls.assert_not_called()


def test_create_mission_plan_is_idempotent_when_active_plan_exists() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    plan_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = _mission(tenant_id=tenant_id, mission_id=mission_id)
    plan_repo = MagicMock()
    plan_repo.create_or_get_active_for_mission.return_value = _plan(
        tenant_id=tenant_id, mission_id=mission_id, plan_id=plan_id
    )

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        first = client.post(f"/v1/missions/{mission_id}/plan", json=_payload())
        second = client.post(f"/v1/missions/{mission_id}/plan", json=_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["plan_id"] == str(plan_id)
    assert second.json()["plan_id"] == str(plan_id)
    assert plan_repo.create_or_get_active_for_mission.call_count == 2


def test_get_returns_tenant_owned_durable_plan() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = _mission(tenant_id=tenant_id, mission_id=mission_id)
    plan_repo = MagicMock()
    plan_repo.get_for_mission.return_value = _plan(tenant_id=tenant_id, mission_id=mission_id)

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/plan")

    assert response.status_code == 200
    assert response.json()["metadata"]["objectives"] == ["Recover stale opportunities."]
    plan_repo.get_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_missing_or_foreign_mission_fails_closed() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.MissionPlanRepository") as plan_repo_cls,
    ):
        post_response = client.post(f"/v1/missions/{mission_id}/plan", json=_payload())
        get_response = client.get(f"/v1/missions/{mission_id}/plan")

    assert post_response.status_code == 404
    assert get_response.status_code == 404
    assert post_response.json() == {"detail": "mission not found for tenant"}
    assert get_response.json() == {"detail": "mission not found for tenant"}
    plan_repo_cls.assert_not_called()


def test_get_missing_plan_is_explicit_and_does_not_create_plan() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id)
    mission.metadata_json = {"mission_intake": {"schema_version": 1}}
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    plan_repo = MagicMock()
    plan_repo.get_for_mission.return_value = None

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/plan")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission plan not found"}
    plan_repo.create_or_get_active_for_mission.assert_not_called()


def test_invalid_metadata_returns_validation_error() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    invalid_payload = _payload()
    invalid_payload["planned_steps"] = [
        {
            "sequence": 1,
            "title": " ",
            "description": "Read approved CRM fields.",
            "unexpected": "field",
        }
    ]

    with patch("backend.api.routes.mission.MissionRepository") as mission_repo_cls:
        response = client.post(f"/v1/missions/{mission_id}/plan", json=invalid_payload)

    assert response.status_code == 422
    mission_repo_cls.assert_not_called()
