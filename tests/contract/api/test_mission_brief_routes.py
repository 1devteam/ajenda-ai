from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission_brief as mission_brief_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.business_profile import BusinessProfile


class _FakeBusinessProfileRepository:
    def __init__(self, _db: object) -> None:
        pass

    def get_active_profile_for_tenant(self, *, tenant_id: str) -> BusinessProfile | None:
        if tenant_id != "11111111-1111-1111-1111-111111111111":
            return None
        return BusinessProfile(
            id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            tenant_id=tenant_id,
            approved_facts={
                "business_name": "Ajenda",
                "allowed_tools": ["crm"],
                "evidence_expectations": ["linked sources"],
            },
        )


def _build_app(*, roles: tuple[str, ...] = ("tenant_admin",)) -> FastAPI:
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
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

    app.include_router(mission_brief_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    return app


def test_mission_brief_draft_is_read_only_and_uses_business_profile_context() -> None:
    app = _build_app()
    with patch.object(mission_brief_module, "BusinessProfileRepository", _FakeBusinessProfileRepository):
        response = TestClient(app).post(
            "/v1/mission-brief/draft",
            json={
                "current_intent": {
                    "objective": "Research buyers",
                    "success_criteria": ["Return five accounts"],
                    "allowed_actions": ["research public sources"],
                },
                "request_context": {"entrypoint": "chat"},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["profile_id"] == "22222222-2222-2222-2222-222222222222"
    assert data["brief"]["profile_context"]["business_name"] == "Ajenda"
    assert data["mission_create_prefill"]["allowed_tools"] == ["crm"]
    assert data["mission_create_prefill"]["context"]["request_context"] == {"entrypoint": "chat"}
    assert data["authority_flags"] == {
        "authority_class": "read_model",
        "read_only": True,
        "creates_mission": False,
        "creates_mission_plan": False,
        "creates_task_graph": False,
        "creates_execution_tasks": False,
        "queues_work": False,
        "dispatches_workers": False,
        "mutates_worker_leases": False,
        "writes_business_profile_truth": False,
        "promotes_memory": False,
        "bypasses_authority_checks": False,
    }


def test_mission_brief_draft_requires_business_profile_read_permission() -> None:
    app = _build_app(roles=("queue_operator",))
    response = TestClient(app).post(
        "/v1/mission-brief/draft",
        json={"current_intent": {"objective": "Research buyers", "success_criteria": ["Return five accounts"]}},
    )

    assert response.status_code == 403


def test_mission_brief_draft_does_not_call_runtime_or_mutation_repositories() -> None:
    app = _build_app()
    with (
        patch.object(mission_brief_module, "BusinessProfileRepository", _FakeBusinessProfileRepository),
        patch("backend.repositories.mission_repository.MissionRepository.add") as mission_add,
        patch(
            "backend.repositories.mission_plan_repository.MissionPlanRepository.create_or_get_active_for_mission"
        ) as plan_add,
        patch("backend.repositories.execution_task_repository.ExecutionTaskRepository.add") as task_add,
        patch("backend.services.mission_executor.MissionExecutor.queue_all_planned_tasks") as queue_all,
        patch("backend.workers.task_dispatcher.TaskDispatcher.execute") as dispatch,
    ):
        response = TestClient(app).post(
            "/v1/mission-brief/draft",
            json={"current_intent": {"objective": "Research buyers", "success_criteria": ["Return five accounts"]}},
        )

    assert response.status_code == 200
    mission_add.assert_not_called()
    plan_add.assert_not_called()
    task_add.assert_not_called()
    queue_all.assert_not_called()
    dispatch.assert_not_called()
