from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.services.execution_coordinator import CoordinationResult
from backend.services.quota_enforcement import QuotaExceededError


def _build_app(tenant_id: uuid.UUID, *, roles: tuple[str, ...] = ("tenant_admin",)) -> FastAPI:
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


def _make_runtime_materialized_mission(
    *, tenant_id: uuid.UUID, mission_id: uuid.UUID, task_ids: list[uuid.UUID]
) -> SimpleNamespace:
    return SimpleNamespace(
        id=mission_id,
        tenant_id=str(tenant_id),
        metadata_json={
            "runtime_task_materialization": {
                "schema_version": 1,
                "materialization_status": "materialized",
                "materialization_version": 1,
                "created_execution_task_ids": [str(task_id) for task_id in task_ids],
            }
        },
    )


def _canonical_admission(task_id: uuid.UUID) -> dict[str, object]:
    return {
        "queued_task_ids": [str(task_id)],
        "pending_review_task_ids": [],
        "denied_tasks": [],
        "admission_status": "admitted",
        "admitted_task_ids": [str(task_id)],
        "blocked_task_ids": [],
        "blockers": [],
        "runtime_queue_admission": {"runtime_authority": {"calls_coordinator": True}},
    }


def test_legacy_queue_delegates_to_canonical_admission_and_projects_response() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    service = MagicMock()
    service.return_value.admit.return_value = _canonical_admission(task_id)

    with (
        patch("backend.api.routes.mission.MissionRuntimeQueueAdmissionService", service),
        patch("backend.services.mission_executor.MissionExecutor.queue_all_planned_tasks") as legacy_queue,
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher,
    ):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 200
    assert response.json() == {
        "queued_task_ids": [str(task_id)],
        "pending_review_task_ids": [],
        "denied_tasks": [],
    }
    service.return_value.admit.assert_called_once_with(mission_id=mission_id, tenant_id=tenant_id)
    legacy_queue.assert_not_called()
    dispatcher.assert_not_called()


def test_both_queue_routes_delegate_to_same_canonical_implementation_and_queue_set() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    service = MagicMock()
    service.return_value.admit.return_value = _canonical_admission(task_id)

    with (
        patch("backend.api.routes.mission.MissionRuntimeQueueAdmissionService", service),
        patch("backend.services.mission_executor.MissionExecutor.queue_all_planned_tasks") as legacy_queue,
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher,
        patch("backend.services.tools.action_registry.ActionRegistry.invoke") as action_invoke,
    ):
        legacy = client.post(f"/v1/missions/{mission_id}/queue")
        canonical = client.post(f"/v1/missions/{mission_id}/runtime-queue-admission")

    assert legacy.status_code == canonical.status_code == 200
    assert legacy.json()["queued_task_ids"] == canonical.json()["queued_task_ids"] == [str(task_id)]
    assert canonical.json()["runtime_queue_admission"] == {"runtime_authority": {"calls_coordinator": True}}
    assert service.return_value.admit.call_count == 2
    assert service.return_value.admit.call_args_list[0] == service.return_value.admit.call_args_list[1]
    legacy_queue.assert_not_called()
    dispatcher.assert_not_called()
    action_invoke.assert_not_called()


@pytest.mark.parametrize(
    "paths",
    [
        ("/runtime-queue-admission", "/queue"),
        ("/queue", "/runtime-queue-admission"),
    ],
)
def test_cross_entrypoint_repeat_uses_one_quota_consumption_and_one_queue_transition(
    paths: tuple[str, str],
) -> None:
    """The second API representation observes the first admission; it cannot re-admit."""
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id)
    mission = _make_runtime_materialized_mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_ids=[task.id],
    )
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [task]
    quota_svc = MagicMock()
    coordinator = MagicMock()

    def _queue_once(*, tenant_id: str, task_id: uuid.UUID) -> CoordinationResult:
        task.status = "queued"
        return CoordinationResult(ok=True, task_id=task_id, state="queued", reason=None)

    coordinator.queue_task.side_effect = _queue_once
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
    ):
        first = client.post(f"/v1/missions/{mission_id}{paths[0]}")
        second = client.post(f"/v1/missions/{mission_id}{paths[1]}")

    assert first.status_code == second.status_code == 200
    assert first.json()["queued_task_ids"] == [str(task.id)]
    assert second.json()["queued_task_ids"] == []
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=1)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=task.id)
    latest_receipt = mission_repo.update_metadata.call_args.kwargs["metadata_json"]["runtime_queue_admission"]
    assert latest_receipt["admitted_execution_task_ids"] == [str(task.id)]
    assert latest_receipt["already_queued_execution_task_ids"] == [str(task.id)]


def test_post_v1_missions_mission_id_runtime_queue_admission_contract_charges_quota_for_eligible_planned_materialized_tasks_only() -> (
    None
):
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    other_mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    eligible_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    queued_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="queued")
    cancelled_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="cancelled")
    foreign_task = _make_task(tenant_id=str(uuid.uuid4()), mission_id=mission_id, status="planned")
    wrong_mission_task = _make_task(tenant_id=str(tenant_id), mission_id=other_mission_id, status="planned")
    missing_task_id = uuid.uuid4()
    mission = _make_runtime_materialized_mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_ids=[
            eligible_task.id,
            queued_task.id,
            cancelled_task.id,
            foreign_task.id,
            wrong_mission_task.id,
            missing_task_id,
        ],
    )

    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [
        eligible_task,
        queued_task,
        cancelled_task,
        foreign_task,
        wrong_mission_task,
    ]
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=True, task_id=eligible_task.id, state="queued", reason=None
    )

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-queue-admission")

    assert response.status_code == 200
    body = response.json()
    assert body["queued_task_ids"] == [str(eligible_task.id)]
    assert body["pending_review_task_ids"] == []
    assert body["denied_tasks"] == []
    assert body["admission_status"] == "partially_admitted"
    assert body["admitted_task_ids"] == [str(queued_task.id), str(eligible_task.id)]
    assert set(body["blocked_task_ids"]) == {
        str(cancelled_task.id),
        str(foreign_task.id),
        str(wrong_mission_task.id),
        str(missing_task_id),
    }
    persisted = mission_repo.update_metadata.call_args.kwargs["metadata_json"]["runtime_queue_admission"]
    assert persisted["admission_status"] == "partially_admitted"
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=1)
    coordinator.queue_task.assert_called_once_with(tenant_id=str(tenant_id), task_id=eligible_task.id)


def test_post_v1_missions_mission_id_runtime_queue_admission_contract_reports_enqueued_denied_pending_review_and_queue_fail_distinctly() -> (
    None
):
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    enqueued_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    denied_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    pending_review_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    queue_fail_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    mission = _make_runtime_materialized_mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_ids=[enqueued_task.id, denied_task.id, pending_review_task.id, queue_fail_task.id],
    )
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [enqueued_task, denied_task, pending_review_task, queue_fail_task]
    quota_svc = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.side_effect = [
        CoordinationResult(ok=True, task_id=enqueued_task.id, state="queued", reason=None),
        CoordinationResult(
            ok=False,
            task_id=denied_task.id,
            state="planned",
            reason="runtime governor denied execution",
        ),
        CoordinationResult(
            ok=False,
            task_id=pending_review_task.id,
            state="pending_review",
            reason="human review required",
        ),
        ValueError("redis unavailable"),
    ]

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-queue-admission")

    assert response.status_code == 200
    body = response.json()
    assert body["admission_status"] == "partially_admitted"
    assert body["queued_task_ids"] == [str(enqueued_task.id)]
    assert body["admitted_task_ids"] == [str(enqueued_task.id)]
    assert body["pending_review_task_ids"] == [str(pending_review_task.id)]
    assert body["denied_tasks"] == [
        {
            "task_id": str(denied_task.id),
            "state": "planned",
            "reason": "runtime governor denied execution",
        }
    ]
    assert set(body["blocked_task_ids"]) == {
        str(denied_task.id),
        str(pending_review_task.id),
        str(queue_fail_task.id),
    }
    blockers_by_task = {blocker["task_id"]: blocker for blocker in body["blockers"]}
    assert blockers_by_task[str(denied_task.id)]["code"] == "runtime_governor_denied"
    assert blockers_by_task[str(pending_review_task.id)]["code"] == "policy_review_required"
    assert blockers_by_task[str(queue_fail_task.id)]["code"] == "queue_task_failed"
    assert blockers_by_task[str(queue_fail_task.id)]["reason"] == "redis unavailable"
    persisted = mission_repo.update_metadata.call_args.kwargs["metadata_json"]["runtime_queue_admission"]
    assert persisted["queued_execution_task_ids"] == [str(enqueued_task.id)]
    assert persisted["pending_review_execution_task_ids"] == [str(pending_review_task.id)]
    assert persisted["denied_tasks"] == body["denied_tasks"]
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=4)
    assert coordinator.queue_task.call_count == 4


def test_post_v1_missions_mission_id_runtime_queue_admission_contract_quota_denial_prevents_queue_calls() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="planned")
    mission = _make_runtime_materialized_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id])
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [task]
    quota_svc = MagicMock()
    quota_svc.check_and_record_task_creation.side_effect = QuotaExceededError(
        field="tasks_per_month", limit=50, current=50, plan="free"
    )
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-queue-admission")

    assert response.status_code == 402
    quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_id, count=1)
    coordinator.queue_task.assert_not_called()


def test_post_v1_missions_mission_id_runtime_queue_admission_contract_skips_queued_and_cancelled_without_quota() -> (
    None
):
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    queued_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="queued")
    cancelled_task = _make_task(tenant_id=str(tenant_id), mission_id=mission_id, status="cancelled")
    mission = _make_runtime_materialized_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued_task.id, cancelled_task.id]
    )
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [queued_task, cancelled_task]
    quota_svc = MagicMock()
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-queue-admission")

    assert response.status_code == 200
    body = response.json()
    assert body["queued_task_ids"] == []
    assert body["pending_review_task_ids"] == []
    assert body["denied_tasks"] == []
    assert body["admission_status"] == "partially_admitted"
    assert body["admitted_task_ids"] == [str(queued_task.id)]
    assert body["blocked_task_ids"] == [str(cancelled_task.id)]
    quota_svc.check_and_record_task_creation.assert_not_called()
    coordinator.queue_task.assert_not_called()


def test_post_v1_missions_mission_id_queue_rejects_viewer_before_side_effects() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=("viewer",))
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()

    with patch("backend.api.routes.mission.MissionRuntimeQueueAdmissionService", service):
        response = client.post(f"/v1/missions/{mission_id}/queue")

    assert response.status_code == 403
    service.assert_not_called()


def test_post_v1_missions_mission_id_runtime_queue_admission_rejects_viewer_before_side_effects() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id, roles=("viewer",))
    client = TestClient(app, raise_server_exceptions=False)

    mission_repo = MagicMock()
    task_repo = MagicMock()
    quota_svc = MagicMock()
    coordinator = MagicMock()

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
    ):
        response = client.post(f"/v1/missions/{mission_id}/runtime-queue-admission")

    assert response.status_code == 403
    mission_repo.lock_for_tenant.assert_not_called()
    task_repo.list_for_mission.assert_not_called()
    quota_svc.check_and_record_task_creation.assert_not_called()
    coordinator.queue_task.assert_not_called()
