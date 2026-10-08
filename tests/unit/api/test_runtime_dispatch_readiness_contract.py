from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.enums import ExecutionTaskState


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


def _make_task(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    status: str = ExecutionTaskState.QUEUED.value,
    task_type: object = "echo",
) -> SimpleNamespace:
    metadata_json: dict[str, object] = {}
    if task_type != "missing":
        metadata_json["task_type"] = task_type
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        status=status,
        metadata_json=metadata_json,
    )


def _make_mission(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    task_ids: list[uuid.UUID] | None,
    materialization: bool = True,
    queue_admission: bool = True,
    admission_status: str = "admitted",
) -> SimpleNamespace:
    metadata_json: dict[str, object] = {}
    if materialization:
        metadata_json["runtime_task_materialization"] = {
            "schema_version": 1,
            "mission_id": str(mission_id),
            "tenant_id": tenant_id,
            "materialization_status": "materialized",
            "materialization_version": 1,
            "created_execution_task_ids": [str(task_id) for task_id in task_ids or []],
        }
    if queue_admission:
        metadata_json["runtime_queue_admission"] = {
            "schema_version": 1,
            "mission_id": str(mission_id),
            "tenant_id": tenant_id,
            "admission_status": admission_status,
            "materialized_execution_task_ids": [str(task_id) for task_id in task_ids or []],
            "admitted_execution_task_ids": [str(task_id) for task_id in task_ids or []],
        }
    return SimpleNamespace(id=mission_id, tenant_id=tenant_id, metadata_json=metadata_json)


def test_runtime_dispatch_readiness_ready_for_queued_materialized_tasks_with_task_type() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id])
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = [queued]

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission_runtime.ExecutionCoordinator") as coordinator_cls,
        patch("backend.services.mission_executor.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission_runtime.task_dispatcher", create=True) as dispatcher,
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "ready"
    assert result.dispatch_ready_task_ids == [str(queued.id)]
    assert result.blocked_task_ids == []
    assert result.runtime_authority.read_only is True
    assert result.runtime_authority.enqueues_work is False
    mission_repo.update_metadata.assert_not_called()
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher.assert_not_called()


def test_runtime_dispatch_readiness_blocked_when_queue_admission_missing() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id], queue_admission=False)
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[queued]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "blocked"
    assert any(blocker["code"] == "runtime_queue_admission_missing" for blocker in result.blockers)


def test_runtime_dispatch_readiness_blocked_when_materialization_missing() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[], materialization=False)
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "blocked"
    assert result.task_count == 0
    assert any(blocker["code"] == "runtime_task_materialization_missing" for blocker in result.blockers)


def test_runtime_dispatch_readiness_blocked_when_materialization_has_no_task_ids() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[])
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "blocked"
    assert any(blocker["code"] == "no_current_materialized_tasks" for blocker in result.blockers)


def test_runtime_dispatch_readiness_partial_for_mixed_materialized_states() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    planned = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.PLANNED.value)
    cancelled = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.CANCELLED.value)
    failed = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.FAILED.value)
    mission = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id, planned.id, cancelled.id, failed.id]
    )
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[queued, planned, cancelled, failed]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "partial"
    assert result.dispatch_ready_task_ids == [str(queued.id)]
    assert result.not_ready_task_ids == [str(planned.id)]
    assert result.skipped_task_ids == [str(cancelled.id)]
    assert result.blocked_task_ids == [str(failed.id)]


def test_runtime_dispatch_readiness_blocks_queued_tasks_missing_task_type_metadata() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    missing = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="missing")
    empty = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="  ")
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[missing.id, empty.id])
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[missing, empty]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "blocked"
    assert set(result.blocked_task_ids) == {str(missing.id), str(empty.id)}
    assert all(blocker["code"] == "queued_task_missing_task_type" for blocker in result.blockers)
    assert {warning["code"] for warning in result.warnings} == {"fallback_handler_not_allowed"}


def test_runtime_dispatch_readiness_blocks_missing_or_scope_mismatched_materialized_task_ids() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    foreign = _make_task(tenant_id=str(uuid.uuid4()), mission_id=mission_id)
    missing_id = uuid.uuid4()
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[foreign.id, missing_id])
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[foreign]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "blocked"
    assert set(result.blocked_task_ids) == {str(foreign.id), str(missing_id)}
    assert {blocker["code"] for blocker in result.blockers} == {
        "materialized_task_scope_mismatch",
        "materialized_task_unavailable",
    }


def test_runtime_dispatch_readiness_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo):
        response = client.get(f"/v1/missions/{mission_id}/runtime-dispatch-readiness")

    assert response.status_code == 404


def test_runtime_dispatch_readiness_blocks_stale_queue_admission_for_new_materialization() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    old_task_id = uuid.uuid4()
    new_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)

    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[new_task.id])
    mission.metadata_json["runtime_queue_admission"]["materialized_execution_task_ids"] = [str(old_task_id)]
    mission.metadata_json["runtime_queue_admission"]["admitted_execution_task_ids"] = [str(old_task_id)]

    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[new_task]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission_runtime.ExecutionCoordinator") as coordinator_cls,
        patch("backend.services.mission_executor.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission_runtime.task_dispatcher", create=True) as dispatcher,
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "blocked"
    assert result.dispatch_ready_task_ids == []
    assert str(new_task.id) in result.blocked_task_ids
    assert {blocker["code"] for blocker in result.blockers} >= {
        "queue_admission_materialization_mismatch",
        "task_not_queue_admitted",
    }
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher.assert_not_called()


def test_runtime_dispatch_readiness_blocks_queued_task_missing_from_current_queue_admission() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    admitted_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    unadmitted_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)

    mission = _make_mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_ids=[admitted_task.id, unadmitted_task.id],
    )
    mission.metadata_json["runtime_queue_admission"]["admitted_execution_task_ids"] = [str(admitted_task.id)]

    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[admitted_task, unadmitted_task]))

    with (
        patch("backend.api.routes.mission_runtime.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission_runtime.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission_runtime.ExecutionCoordinator") as coordinator_cls,
        patch("backend.services.mission_executor.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission_runtime.task_dispatcher", create=True) as dispatcher,
    ):
        result = mission_module.read_mission_runtime_dispatch_readiness(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.readiness_status == "partial"
    assert result.dispatch_ready_task_ids == [str(admitted_task.id)]
    assert result.blocked_task_ids == [str(unadmitted_task.id)]
    assert any(blocker["code"] == "task_not_queue_admitted" for blocker in result.blockers)
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher.assert_not_called()
