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
from backend.domain.mission import MissionPlan, build_mission_plan_contract_metadata_from_legacy_write


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


def test_timeline_prefers_durable_plan_over_legacy_metadata() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    plan_updated_at = datetime(2026, 5, 25, 12, 7, tzinfo=UTC)

    mission = SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        status="planned",
        created_at=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, 12, 10, tzinfo=UTC),
        metadata_json={
            "mission_plan": {
                "planning_status": "stale-metadata",
                "updated_at": datetime(2026, 5, 25, 12, 1, tzinfo=UTC).isoformat(),
            }
        },
    )
    durable_plan = MissionPlan(
        id=uuid.uuid4(),
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        status="ready",
        metadata_json=build_mission_plan_contract_metadata_from_legacy_write(
            planning_status="approved",
            phases=[{"name": "Research", "objective": "Durable objective", "stages": []}],
            planning_notes=None,
            desired_outputs=[],
            capability_requirements=[],
            execution_strategy_hints={},
            approval_gates=[],
            operator_overrides={},
            estimated_scope={},
            risk_annotations=[],
        ),
    )
    durable_plan.created_at = plan_updated_at
    durable_plan.updated_at = plan_updated_at

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = []
    plan_repo = MagicMock()
    plan_repo.get_for_mission.return_value = durable_plan

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.MissionPlanRepository", return_value=plan_repo),
    ):
        response = client.get(f"/v1/missions/{mission_id}/timeline")

    assert response.status_code == 200
    plan_events = [event for event in response.json()["events"] if event["stage"] == "mission_plan"]
    assert len(plan_events) == 1
    assert plan_events[0]["source"] == "mission_plan"
    assert plan_events[0]["details"]["status"] == "approved"
    assert plan_events[0]["details"]["plan_id"] == str(durable_plan.id)
