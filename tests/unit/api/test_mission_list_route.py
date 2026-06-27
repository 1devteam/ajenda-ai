from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, Mission


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

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _mission(*, tenant_id: str, objective: str, status: str = "planned") -> Mission:
    now = datetime.now(UTC)
    mission = Mission(
        tenant_id=tenant_id,
        objective=objective,
        status=status,
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={
            MISSION_INTAKE_METADATA_KEY: {
                "scope_limits": ["Austin metro"],
                "allowed_actions": ["web.search", "gtm.email_draft"],
            }
        },
    )
    mission.id = uuid.uuid4()
    mission.created_at = now
    mission.updated_at = now
    return mission


def test_list_missions_returns_newest_first_summary(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    repo = MagicMock()
    older = _mission(tenant_id=str(tenant_id), objective="Older roofing mission in Austin.")
    newer = _mission(tenant_id=str(tenant_id), objective="Find three qualified roofing leads in Austin.", status="running")
    repo.list_by_tenant.return_value = [newer, older]
    monkeypatch.setattr(mission_module, "MissionRepository", lambda _db: repo)

    client = TestClient(app)
    response = client.get("/v1/missions?limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["missions"][0]["mission_id"] == str(newer.id)
    assert body["missions"][0]["status"] == "running"
    assert body["missions"][0]["allowed_actions"] == ["web.search", "gtm.email_draft"]
    repo.list_by_tenant.assert_called_once_with(str(tenant_id), limit=10)