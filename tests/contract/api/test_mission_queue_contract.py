from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.services.mission_executor import MissionQueueSummary, MissionTaskDenial


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(mission_module.router, prefix="/v1")

    def _override_tenant_id():
        return tenant_id

    def _override_db():
        return MagicMock()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def _make_task(*, tenant_id: str, mission_id: uuid.UUID, status: str = "planned") -> MagicMock:
    task = MagicMock()
    task.id = uuid.uuid4()
    task.tenant_id = tenant_id
    task.mission_id = mission_id
    task.status = status
    return task


def test_mission_queue_contract_returns_empty_shape_when_no_planned_tasks() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = []
    quota_svc = MagicMock()
    executor = MagicMock()

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
        patch("backend.api.routes.mission.ExecutionCoordinator"),
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queued_task_ids": [],
        "pending_review_task_ids": [],
        "denied_tasks": [],
    }
    quota_svc.check_and_record_task_creation.assert_not_called()
    executor.queue_all_planned_tasks.assert_not_called()


def test_mission_queue_contract_returns_truthful_mixed_outcome_summary() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    queued_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id)
    pending_review_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id)
    denied_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id)

    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [queued_task, pending_review_task, denied_task]

    quota_svc = MagicMock()
    executor = MagicMock()
    executor.queue_all_planned_tasks.return_value = MissionQueueSummary(
        queued_task_ids=[queued_task.id],
        pending_review_task_ids=[pending_review_task.id],
        denied_tasks=[
            MissionTaskDenial(
                task_id=denied_task.id,
                state="blocked",
                reason="runtime governor denied execution",
            )
        ],
    )

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
        patch("backend.api.routes.mission.ExecutionCoordinator"),
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queued_task_ids": [str(queued_task.id)],
        "pending_review_task_ids": [str(pending_review_task.id)],
        "denied_tasks": [
            {
                "task_id": str(denied_task.id),
                "state": "blocked",
                "reason": "runtime governor denied execution",
            }
        ],
    }
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=3)
    executor.queue_all_planned_tasks.assert_called_once_with(tenant_id=str(tenant_id), mission_id=mission_id)


def test_mission_queue_contract_counts_only_planned_tasks_for_quota() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    planned_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    queued_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="queued")
    completed_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="completed")

    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [planned_task, queued_task, completed_task]

    quota_svc = MagicMock()
    executor = MagicMock()
    executor.queue_all_planned_tasks.return_value = MissionQueueSummary(
        queued_task_ids=[planned_task.id],
        pending_review_task_ids=[],
        denied_tasks=[],
    )

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
        patch("backend.api.routes.mission.ExecutionCoordinator"),
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queued_task_ids": [str(planned_task.id)],
        "pending_review_task_ids": [],
        "denied_tasks": [],
    }
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=1)
    executor.queue_all_planned_tasks.assert_called_once_with(tenant_id=str(tenant_id), mission_id=mission_id)


def test_mission_queue_contract_ignores_foreign_tenant_planned_tasks_for_quota_and_execution() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    foreign_planned_task = _make_task(
        tenant_id=str(other_tenant_id),
        mission_id=mission_id,
        status="planned",
    )

    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [foreign_planned_task]
    quota_svc = MagicMock()
    executor = MagicMock()

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
        patch("backend.api.routes.mission.ExecutionCoordinator"),
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queued_task_ids": [],
        "pending_review_task_ids": [],
        "denied_tasks": [],
    }
    quota_svc.check_and_record_task_creation.assert_not_called()
    executor.queue_all_planned_tasks.assert_not_called()


def test_mission_queue_contract_counts_only_local_planned_tasks_when_mission_contains_foreign_work() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    local_planned_task = _make_task(
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        status="planned",
    )
    foreign_planned_task = _make_task(
        tenant_id=str(other_tenant_id),
        mission_id=mission_id,
        status="planned",
    )

    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [local_planned_task, foreign_planned_task]
    quota_svc = MagicMock()
    executor = MagicMock()
    executor.queue_all_planned_tasks.return_value = MissionQueueSummary(
        queued_task_ids=[local_planned_task.id],
        pending_review_task_ids=[],
        denied_tasks=[],
    )

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
        patch("backend.api.routes.mission.ExecutionCoordinator"),
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queued_task_ids": [str(local_planned_task.id)],
        "pending_review_task_ids": [],
        "denied_tasks": [],
    }
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=1)
    executor.queue_all_planned_tasks.assert_called_once_with(tenant_id=str(tenant_id), mission_id=mission_id)
