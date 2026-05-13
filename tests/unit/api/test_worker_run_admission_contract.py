from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(mission_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    def _override_queue() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def _make_task(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    status: str = ExecutionTaskState.RUNNING.value,
    task_type: object = "echo",
    worker_lease_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    metadata_json: dict[str, object] = {"runtime_task_type": "echo", "graph_node_key": "collect-signals"}
    if task_type != "missing":
        metadata_json["task_type"] = task_type
    if worker_lease_id is not None:
        metadata_json["worker_lease_id"] = str(worker_lease_id)
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, mission_id=mission_id, status=status, metadata_json=metadata_json
    )


def _make_lease(
    *,
    tenant_id: str,
    task_id: uuid.UUID,
    holder_identity: str,
    status: str = WorkerLeaseState.ACTIVE.value,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=task_id,
        holder_identity=holder_identity,
        status=status,
        heartbeat_at=None,
    )


def _make_mission(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    tasks: list[SimpleNamespace],
    leases: list[SimpleNamespace] | None = None,
    start_status: str = "admitted",
) -> SimpleNamespace:
    start_receipts = []
    for task in tasks:
        lease = next((candidate for candidate in leases or [] if candidate.task_id == task.id), None)
        start_receipts.append(
            {
                "task_id": str(task.id),
                "tenant_id": tenant_id,
                "mission_id": str(mission_id),
                "previous_task_state": "claimed",
                "current_task_state": "running",
                "worker_lease_id": str(lease.id) if lease is not None else None,
                "lease_scope": {"tenant_id": tenant_id, "mission_id": str(mission_id), "task_id": str(task.id)},
                "start_source": "worker_start_admission",
                "task_type": "echo",
                "started_at": "2026-05-12T00:00:00+00:00",
                "idempotency_status": "newly_started",
            }
        )
    return SimpleNamespace(
        id=mission_id,
        tenant_id=tenant_id,
        metadata_json={
            "runtime_task_materialization": {"metadata_key": "runtime_task_materialization"},
            "runtime_queue_admission": {"metadata_key": "runtime_queue_admission"},
            "worker_claim_admission": {"metadata_key": "worker_claim_admission"},
            "worker_start_admission": {
                "schema_version": 1,
                "mission_id": str(mission_id),
                "tenant_id": tenant_id,
                "admission_status": start_status,
                "admission_version": 1,
                "started_task_ids": [str(task.id) for task in tasks],
                "already_started_task_ids": [],
                "skipped_task_ids": [],
                "blocked_task_ids": [],
                "start_receipts": start_receipts,
                "blockers": [],
                "warnings": [],
                "materialization_reference": {"metadata_key": "runtime_task_materialization"},
                "queue_admission_reference": {"metadata_key": "runtime_queue_admission"},
                "dispatch_readiness_summary": {"readiness_status": "ready"},
                "worker_dispatch_eligibility_summary": {"preview_status": "ready"},
                "worker_claim_preview_reference": {"preview_status": "ready"},
                "worker_claim_admission_reference": {"admission_status": "admitted"},
                "updated_at": "2026-05-12T00:00:00+00:00",
            },
        },
    )


def _repos(mission: SimpleNamespace, tasks: list[SimpleNamespace], leases: list[SimpleNamespace]):
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    mission_repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission: SimpleNamespace, metadata_json: dict[str, object]) -> SimpleNamespace:
        mission.metadata_json = metadata_json
        return mission

    mission_repo.update_metadata.side_effect = _update_metadata
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=tasks))
    tasks_by_id = {task.id: task for task in tasks}
    task_repo.get.side_effect = lambda task_id: tasks_by_id.get(task_id)
    leases_by_id = {lease.id: lease for lease in leases}
    lease_repo = MagicMock()
    lease_repo.get.side_effect = lambda lease_id: leases_by_id.get(lease_id)
    lease_repo.list_for_task.side_effect = lambda task_id: [lease for lease in leases if lease.task_id == task_id]
    return mission_repo, task_repo, lease_repo


def _admit(
    mission: SimpleNamespace, tasks: list[SimpleNamespace], leases: list[SimpleNamespace], dispatch
) -> mission_module.WorkerRunAdmissionRead:
    tenant_uuid = uuid.UUID(mission.tenant_id)
    mission_repo, task_repo, lease_repo = _repos(mission, tasks, leases)
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission._dispatch_worker_run_task", side_effect=dispatch) as dispatcher,
    ):
        result = mission_module.worker_run_admission(
            mission_id=mission.id,
            request=MagicMock(headers={}),
            tenant_id=tenant_uuid,
            db=MagicMock(),
            queue=MagicMock(),
        )
    result._dispatcher_mock = dispatcher  # type: ignore[attr-defined]
    return result


def test_worker_run_admission_executes_running_task_and_persists_receipt() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])

    def dispatch(**kwargs) -> None:
        task.status = ExecutionTaskState.COMPLETED.value
        lease.status = WorkerLeaseState.RELEASED.value

    result = _admit(mission, [task], [lease], dispatch)

    assert result.run_admission_status == "completed"
    assert result.executed_task_ids == [str(task.id)]
    assert result.completed_task_ids == [str(task.id)]
    assert result.run_receipts[0].idempotency_status == "newly_executed"
    assert result.run_receipts[0].worker_lease_id == str(lease.id)
    assert result.worker_run_authority.dispatches_workers is True
    assert result.worker_run_authority.executes_handlers is True
    assert result.worker_run_authority.enqueues_work is False
    assert mission.metadata_json["worker_run_admission"]["run_receipts"][0]["task_id"] == str(task.id)
    assert result._dispatcher_mock.call_count == 1  # type: ignore[attr-defined]


def test_worker_run_admission_failure_persists_failure_receipt_and_blocker() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="force_fail")
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])

    def dispatch(**kwargs) -> None:
        task.status = ExecutionTaskState.FAILED.value
        lease.status = WorkerLeaseState.RELEASED.value

    result = _admit(mission, [task], [lease], dispatch)

    assert result.run_admission_status == "failed"
    assert result.failed_task_ids == [str(task.id)]
    assert result.run_receipts[0].current_task_state == "failed"
    assert result.run_receipts[0].error_summary is not None
    assert any(blocker["code"] == "handler_execution_failed" for blocker in result.blockers)


def test_worker_run_admission_retries_are_idempotent_and_do_not_dispatch_again() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])

    def dispatch(**kwargs) -> None:
        task.status = ExecutionTaskState.COMPLETED.value
        lease.status = WorkerLeaseState.RELEASED.value

    first = _admit(mission, [task], [lease], dispatch)
    first_receipt = copy.deepcopy(mission.metadata_json["worker_run_admission"]["run_receipts"][0])
    second = _admit(mission, [task], [lease], dispatch)
    third = _admit(mission, [task], [lease], dispatch)

    assert first.run_receipts[0].idempotency_status == "newly_executed"
    assert second.already_completed_task_ids == [str(task.id)]
    assert third.already_completed_task_ids == [str(task.id)]
    assert second.run_receipts[0].idempotency_status == "already_completed_by_current_run_admission"
    assert third.run_receipts[0].worker_lease_id == first_receipt["worker_lease_id"]
    assert third.run_receipts[0].executed_at == first_receipt["executed_at"]
    assert second._dispatcher_mock.call_count == 0  # type: ignore[attr-defined]
    assert third._dispatcher_mock.call_count == 0  # type: ignore[attr-defined]


def test_worker_run_admission_blocks_missing_start_stale_receipt_lease_task_type_and_bad_states() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)

    missing_start = SimpleNamespace(id=mission_id, tenant_id=tenant_id, metadata_json={})
    missing = _admit(missing_start, [task], [lease], lambda **kwargs: None)
    assert missing.run_admission_status == "blocked"
    assert missing.blockers[0]["code"] == "worker_start_admission_missing"

    stale = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease], start_status="blocked"
    )
    stale_result = _admit(stale, [task], [lease], lambda **kwargs: None)
    assert stale_result.blockers[0]["code"] == "worker_start_admission_not_admitted"

    cases: list[tuple[str, SimpleNamespace, list[SimpleNamespace], str]] = []
    no_receipt = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    no_receipt.metadata_json["worker_start_admission"]["start_receipts"] = []
    cases.append(("missing receipt", no_receipt, [lease], "worker_start_receipt_missing"))

    no_lease_id_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    no_lease = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[no_lease_id_task], leases=[])
    cases.append(("missing lease id", no_lease, [], "worker_lease_id_missing"))

    missing_type_task = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="missing")
    missing_type_lease = _make_lease(tenant_id=tenant_id, task_id=missing_type_task.id, holder_identity=holder)
    missing_type_task.metadata_json["worker_lease_id"] = str(missing_type_lease.id)
    missing_type = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, tasks=[missing_type_task], leases=[missing_type_lease]
    )
    cases.append(("missing task type", missing_type, [missing_type_lease], "run_task_missing_task_type"))

    inactive_lease = _make_lease(
        tenant_id=tenant_id, task_id=task.id, holder_identity=holder, status=WorkerLeaseState.RELEASED.value
    )
    task.metadata_json["worker_lease_id"] = str(inactive_lease.id)
    inactive = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[inactive_lease])
    cases.append(("inactive lease", inactive, [inactive_lease], "worker_lease_inactive"))

    queued_task = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.QUEUED.value)
    queued_lease = _make_lease(tenant_id=tenant_id, task_id=queued_task.id, holder_identity=holder)
    queued_task.metadata_json["worker_lease_id"] = str(queued_lease.id)
    queued = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[queued_task], leases=[queued_lease])
    cases.append(("bad state", queued, [queued_lease], "run_task_not_running"))

    for _label, mission, leases, expected_code in cases:
        current_tasks = [
            candidate
            for candidate in [task, no_lease_id_task, missing_type_task, queued_task]
            if candidate.mission_id == mission.id
        ]
        result = _admit(mission, current_tasks, leases, lambda **kwargs: None)
        assert result.run_admission_status == "blocked"
        assert any(blocker["code"] == expected_code for blocker in result.blockers)
        assert result._dispatcher_mock.call_count == 0  # type: ignore[attr-defined]


def test_worker_run_admission_partial_completion_and_authority_non_goals() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    completed = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    failed = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="force_fail")
    leases = [
        _make_lease(tenant_id=tenant_id, task_id=completed.id, holder_identity=holder),
        _make_lease(tenant_id=tenant_id, task_id=failed.id, holder_identity=holder),
    ]
    completed.metadata_json["worker_lease_id"] = str(leases[0].id)
    failed.metadata_json["worker_lease_id"] = str(leases[1].id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[completed, failed], leases=leases)
    original_contracts = {
        key: copy.deepcopy(mission.metadata_json[key])
        for key in [
            "runtime_task_materialization",
            "runtime_queue_admission",
            "worker_claim_admission",
            "worker_start_admission",
        ]
    }

    def dispatch(**kwargs) -> None:
        if kwargs["task_id"] == completed.id:
            completed.status = ExecutionTaskState.COMPLETED.value
            leases[0].status = WorkerLeaseState.RELEASED.value
        else:
            failed.status = ExecutionTaskState.FAILED.value
            leases[1].status = WorkerLeaseState.RELEASED.value

    with (
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
    ):
        result = _admit(mission, [completed, failed], leases, dispatch)

    assert result.run_admission_status == "partially_completed"
    assert result.completed_task_ids == [str(completed.id)]
    assert result.failed_task_ids == [str(failed.id)]
    assert result.worker_run_authority.enqueues_work is False
    assert {key: mission.metadata_json[key] for key in original_contracts} == original_contracts
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()


def test_worker_run_admission_get_returns_latest_metadata_and_missing_is_read_only_blocked() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[])
    admission = {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": "completed",
        "admission_version": 1,
        "executed_task_ids": [str(uuid.uuid4())],
        "completed_task_ids": [],
        "failed_task_ids": [],
        "already_completed_task_ids": [],
        "already_failed_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "run_receipts": [],
        "blockers": [],
        "warnings": [],
        "runtime_authority": {"dispatches_workers": True, "read_only": False},
        "updated_at": "2026-05-12T00:00:00+00:00",
    }
    mission.metadata_json["worker_run_admission"] = admission
    mission_repo, _, _ = _repos(mission, [], [])

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        result = mission_module.read_mission_worker_run_admission(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.run_admission_status == "completed"
    assert result.worker_run_authority.read_only is True
    assert result.worker_run_authority.dispatches_workers is False
    mission_repo.update_metadata.assert_not_called()

    missing = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[])
    missing_repo = MagicMock(get_for_tenant=MagicMock(return_value=missing))
    with patch("backend.api.routes.mission.MissionRepository", return_value=missing_repo):
        missing_result = mission_module.read_mission_worker_run_admission(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert missing_result.run_admission_status == "blocked"
    assert missing_result.worker_run_authority.read_only is True
    assert missing_result.blockers[0]["code"] == "worker_run_admission_missing"
    missing_repo.update_metadata.assert_not_called()


def test_worker_run_admission_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock(lock_for_tenant=MagicMock(return_value=None))

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/worker-run-admission")

    assert response.status_code == 404
