from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.queue.base import QueueMessage
from backend.queue.local_adapter import LocalQueueAdapter


def _task(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    status: str = "running",
    task_type: object = "echo",
    lease_id: uuid.UUID | None = None,
    retry_count: int = 0,
):
    metadata: dict[str, object] = {"runtime_task_type": "echo", "graph_node_key": "collect"}
    if task_type != "missing":
        metadata["task_type"] = task_type
    if lease_id:
        metadata["worker_lease_id"] = str(lease_id)
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        fleet_id=None,
        branch_id=None,
        status=status,
        metadata_json=metadata,
        retry_count=retry_count,
    )


def _lease(*, tenant_id: str, task_id: uuid.UUID, mission_id: uuid.UUID, holder: str, status: str = "active"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=task_id,
        status=status,
        holder_identity=holder,
        heartbeat_at=datetime.now(UTC),
        metadata_json={"mission_id": str(mission_id)},
    )


def _mission(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    tasks: list[SimpleNamespace],
    leases: list[SimpleNamespace],
    start_status: str = "admitted",
):
    receipts = []
    for task, lease in zip(tasks, leases, strict=True):
        receipts.append(
            {
                "task_id": str(task.id),
                "tenant_id": tenant_id,
                "mission_id": str(mission_id),
                "previous_task_state": "claimed",
                "current_task_state": "running",
                "worker_lease_id": str(lease.id),
                "lease_scope": {"tenant_id": tenant_id, "mission_id": str(mission_id), "task_id": str(task.id)},
                "start_source": "worker_start_admission",
                "task_type": task.metadata_json.get("task_type"),
                "started_at": getattr(task, "started_at", "2026-05-13T00:00:00+00:00"),
                "retry_count": getattr(task, "retry_count", 0),
                "idempotency_status": "newly_started",
            }
        )
    return SimpleNamespace(
        id=mission_id,
        tenant_id=tenant_id,
        metadata_json={
            "runtime_task_materialization": {"materialization_status": "materialized"},
            "runtime_queue_admission": {"admission_status": "admitted"},
            "worker_claim_admission": {"admission_status": "admitted", "admission_version": 1},
            "worker_start_admission": {
                "schema_version": 1,
                "mission_id": str(mission_id),
                "tenant_id": tenant_id,
                "admission_status": start_status,
                "admission_version": 1,
                "started_task_ids": [str(task.id) for task in tasks],
                "start_receipts": receipts,
                "materialization_reference": {"metadata_key": "runtime_task_materialization"},
                "queue_admission_reference": {"metadata_key": "runtime_queue_admission"},
                "dispatch_readiness_summary": {"readiness_status": "ready"},
                "worker_dispatch_eligibility_summary": {"eligibility_status": "eligible"},
                "worker_claim_preview_reference": {"preview_status": "ready"},
                "worker_claim_admission_reference": {"admission_status": "admitted"},
                "updated_at": "2026-05-13T00:00:00+00:00",
            },
        },
    )


def _repos(mission: SimpleNamespace, tasks: list[SimpleNamespace], leases: list[SimpleNamespace]):
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    mission_repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission: SimpleNamespace, metadata_json: dict[str, object]):
        mission.metadata_json = metadata_json
        return mission

    mission_repo.update_metadata.side_effect = _update_metadata
    task_repo = MagicMock()
    task_repo.list_for_mission.return_value = tasks
    task_repo.get.side_effect = lambda task_id: next((task for task in tasks if task.id == task_id), None)
    lease_repo = MagicMock()
    lease_repo.get.side_effect = lambda lease_id: next((lease for lease in leases if lease.id == lease_id), None)
    lease_repo.list_for_task.side_effect = lambda task_id: [lease for lease in leases if lease.task_id == task_id]
    return mission_repo, task_repo, lease_repo


class _AnyTenantId:
    def __eq__(self, _other: object) -> bool:
        return True

    def __ne__(self, _other: object) -> bool:
        return False


def _request() -> MagicMock:
    session = MagicMock()
    session.execute = MagicMock()
    runtime = SimpleNamespace(session_factory=MagicMock(return_value=session))
    request = MagicMock(headers={})
    request.state.principal = SimpleNamespace(
        subject_id="test-user",
        tenant_id=_AnyTenantId(),
        roles=("operator",),
        permissions=frozenset(),
    )
    request.app.state.database_runtime = runtime
    return request


def _queue_with_task(tenant_id: str, mission_id: uuid.UUID, task_id: uuid.UUID) -> LocalQueueAdapter:
    queue = LocalQueueAdapter()
    queue.enqueue_task(
        QueueMessage(
            tenant_id=tenant_id,
            task_id=task_id,
            mission_id=mission_id,
            fleet_id=None,
            branch_id=None,
            payload={"safe": "payload"},
            enqueued_at=datetime.now(UTC),
        )
    )
    return queue


def test_worker_run_admission_applies_tenant_context_to_dispatcher_sessions() -> None:
    tenant_id = str(uuid.uuid4())
    fake_session = MagicMock()
    runtime = SimpleNamespace(session_factory=MagicMock(return_value=fake_session))
    request = MagicMock()
    request.app.state.database_runtime = runtime

    factory = mission_module._tenant_aware_dispatcher_session_factory(request=request, tenant_id=tenant_id)
    session = factory()

    assert session is fake_session
    assert factory.tenant_id == tenant_id
    assert factory.rls_context_applied is True
    fake_session.execute.assert_called_once()
    assert fake_session.execute.call_args.args[1] == {"tenant_id": tenant_id}


def test_worker_run_admission_claims_local_queue_before_dispatch_and_completes() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])
    queue = _queue_with_task(tenant_id, mission_id, task.id)

    def _execute(*, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        assert (tenant_id, task_id) in queue._claims
        assert queue._claims[(tenant_id, task_id)][0] == holder
        result = queue.complete_task(tenant_id=tenant_id, task_id=task_id, worker_id=holder)
        assert result.ok
        task.status = ExecutionTaskState.COMPLETED.value
        lease.status = WorkerLeaseState.RELEASED.value

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        dispatcher_cls.return_value.execute.side_effect = _execute
        result = mission_module.worker_run_admission(
            mission_id=mission_id, request=_request(), tenant_id=tenant_uuid, db=MagicMock(), queue=queue
        )

    assert result.run_admission_status == "completed"
    assert result.executed_task_ids == [str(task.id)]
    assert result.completed_task_ids == [str(task.id)]
    assert result.run_receipts[0].queue_claim["claimed"] is True
    assert result.run_receipts[0].current_task_state == "completed"
    assert result.worker_run_authority.dispatches_workers is True
    assert (tenant_id, task.id) not in queue._claims
    dispatcher_cls.return_value.execute.assert_called_once_with(task_id=task.id, lease_id=lease.id)


def test_worker_run_admission_blocks_missing_queue_payload_and_keeps_task_running() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=LocalQueueAdapter(),
        )

    assert result.run_admission_status == "blocked"
    assert result.blocked_task_ids == [str(task.id)]
    assert result.blockers[0]["code"] == "queue_claim_unavailable"
    assert task.status == ExecutionTaskState.RUNNING.value
    dispatcher_cls.return_value.execute.assert_not_called()


def test_worker_run_admission_blocks_queue_payload_owned_by_another_worker() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])
    queue = _queue_with_task(tenant_id, mission_id, task.id)
    assert queue.claim_existing_task(tenant_id=tenant_id, task_id=task.id, worker_id="other-worker").ok

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=queue,
        )

    assert result.run_admission_status == "blocked"
    assert result.blockers[0]["details"]["reason"] == "task already claimed by different worker"
    dispatcher_cls.return_value.execute.assert_not_called()


def test_worker_run_admission_is_idempotent_after_completion() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])
    queue = _queue_with_task(tenant_id, mission_id, task.id)

    def _execute(*, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        assert queue.complete_task(tenant_id=tenant_id, task_id=task_id, worker_id=holder).ok
        task.status = ExecutionTaskState.COMPLETED.value
        lease.status = WorkerLeaseState.RELEASED.value

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        dispatcher_cls.return_value.execute.side_effect = _execute
        first = mission_module.worker_run_admission(
            mission_id=mission_id, request=_request(), tenant_id=uuid.UUID(tenant_id), db=MagicMock(), queue=queue
        )
        second = mission_module.worker_run_admission(
            mission_id=mission_id, request=_request(), tenant_id=uuid.UUID(tenant_id), db=MagicMock(), queue=queue
        )
        third = mission_module.worker_run_admission(
            mission_id=mission_id, request=_request(), tenant_id=uuid.UUID(tenant_id), db=MagicMock(), queue=queue
        )

    assert first.run_admission_status == "completed"
    assert second.already_completed_task_ids == [str(task.id)]
    assert third.already_completed_task_ids == [str(task.id)]
    assert dispatcher_cls.return_value.execute.call_count == 1
    assert second.run_receipts[0].worker_lease_id == first.run_receipts[0].worker_lease_id
    assert third.run_receipts[0].executed_at == first.run_receipts[0].executed_at


def test_get_worker_run_admission_missing_is_read_only() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = FastAPI()
    app.include_router(mission_module.router, prefix="/v1")
    mission = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id), metadata_json={})
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))

    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        client = TestClient(app)
        response = client.get(f"/v1/missions/{mission_id}/worker-run-admission")

    assert response.status_code == 200
    body = response.json()
    assert body["run_admission_status"] == "blocked"
    assert body["worker_run_authority"]["read_only"] is True
    assert body["worker_run_authority"]["mutates_runtime_state"] is False


def test_local_queue_claim_existing_task_same_owner_is_idempotent() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    queue = _queue_with_task(tenant_id, mission_id, task_id)

    first = queue.claim_existing_task(tenant_id=tenant_id, task_id=task_id, worker_id="owner")
    second = queue.claim_existing_task(tenant_id=tenant_id, task_id=task_id, worker_id="owner")

    assert first.ok is True
    assert second.ok is True
    assert queue.complete_task(tenant_id=tenant_id, task_id=task_id, worker_id="owner").ok is True


def _existing_run_receipt(
    *,
    task: SimpleNamespace,
    lease: SimpleNamespace,
    current_state: str,
    idempotency_status: str = "newly_executed",
    started_from_admission_at: str = "2026-05-13T00:00:00+00:00",
    retry_count: int | None = None,
) -> dict[str, object]:
    resolved_retry_count = getattr(task, "retry_count", 0) if retry_count is None else retry_count
    return {
        "task_id": str(task.id),
        "tenant_id": task.tenant_id,
        "mission_id": str(task.mission_id),
        "previous_task_state": "running",
        "current_task_state": current_state,
        "worker_lease_id": str(lease.id),
        "lease_scope": {"tenant_id": task.tenant_id, "mission_id": str(task.mission_id), "task_id": str(task.id)},
        "queue_claim": {"claimed": True, "owner": lease.holder_identity, "adapter": "LocalQueueAdapter"},
        "run_source": "worker_run_admission",
        "task_type": task.metadata_json.get("task_type"),
        "handler_name": task.metadata_json.get("task_type"),
        "handler_key": task.metadata_json.get("task_type"),
        "started_from_admission_at": started_from_admission_at,
        "retry_count": resolved_retry_count,
        "attempt_identity": {
            "task_id": str(task.id),
            "worker_lease_id": str(lease.id),
            "started_from_admission_at": started_from_admission_at,
            "retry_count": resolved_retry_count,
        },
        "executed_at": "2026-05-13T00:01:00+00:00",
        "completed_at": "2026-05-13T00:02:00+00:00" if current_state == ExecutionTaskState.COMPLETED.value else None,
        "failed_at": "2026-05-13T00:02:00+00:00"
        if current_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}
        else None,
        "result_summary": {"task_type": task.metadata_json.get("task_type")},
        "error_summary": {"message": "previous failure"}
        if current_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}
        else None,
        "idempotency_status": idempotency_status,
    }


def _set_existing_run_admission(
    *,
    mission: SimpleNamespace,
    task: SimpleNamespace,
    lease: SimpleNamespace,
    current_state: str,
    started_from_admission_at: str = "2026-05-13T00:00:00+00:00",
    retry_count: int | None = None,
) -> dict[str, object]:
    receipt = _existing_run_receipt(
        task=task,
        lease=lease,
        current_state=current_state,
        started_from_admission_at=started_from_admission_at,
        retry_count=retry_count,
    )
    mission.metadata_json["worker_run_admission"] = {
        "schema_version": 1,
        "mission_id": str(mission.id),
        "tenant_id": mission.tenant_id,
        "admission_status": "completed" if current_state == ExecutionTaskState.COMPLETED.value else "failed",
        "admission_version": 1,
        "executed_task_ids": [str(task.id)],
        "completed_task_ids": [str(task.id)] if current_state == ExecutionTaskState.COMPLETED.value else [],
        "failed_task_ids": [str(task.id)]
        if current_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value}
        else [],
        "already_completed_task_ids": [],
        "already_failed_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "run_receipts": [receipt],
        "blockers": [],
        "warnings": [],
        "queue_claim_receipts": [],
        "tenant_session_context": {"tenant_id": mission.tenant_id, "rls_context_applied": True},
        "runtime_authority": mission_module._worker_run_admission_authority_flags(
            completed=current_state == ExecutionTaskState.COMPLETED.value,
            failed=current_state in {ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value},
        ).model_dump(),
        "updated_at": "2026-05-13T00:02:00+00:00",
    }
    return receipt


def test_worker_run_admission_rechecks_nonterminal_prior_receipt_and_retries_when_live_state_valid() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    _set_existing_run_admission(mission=mission, task=task, lease=lease, current_state=ExecutionTaskState.RUNNING.value)
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])
    queue = _queue_with_task(tenant_id, mission_id, task.id)

    def _execute(*, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        assert queue.complete_task(tenant_id=tenant_id, task_id=task_id, worker_id=holder).ok
        task.status = ExecutionTaskState.COMPLETED.value
        lease.status = WorkerLeaseState.RELEASED.value

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        dispatcher_cls.return_value.execute.side_effect = _execute
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=queue,
        )

    assert result.run_admission_status == "completed"
    assert result.already_failed_task_ids == []
    assert result.executed_task_ids == [str(task.id)]
    assert result.completed_task_ids == [str(task.id)]
    dispatcher_cls.return_value.execute.assert_called_once_with(task_id=task.id, lease_id=lease.id)


def test_worker_run_admission_rechecks_nonterminal_prior_receipt_and_blocks_on_missing_queue_payload() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    prior_receipt = _set_existing_run_admission(
        mission=mission, task=task, lease=lease, current_state=ExecutionTaskState.RUNNING.value
    )
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=LocalQueueAdapter(),
        )

    assert result.run_admission_status == "blocked"
    assert result.already_failed_task_ids == []
    assert result.blocked_task_ids == [str(task.id)]
    assert result.blockers[0]["code"] == "queue_claim_unavailable"
    assert mission.metadata_json["worker_run_admission"]["run_receipts"] == []
    assert prior_receipt["current_task_state"] == ExecutionTaskState.RUNNING.value
    dispatcher_cls.return_value.execute.assert_not_called()


def test_worker_run_admission_prior_completed_receipt_remains_idempotent_without_dispatch() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.COMPLETED.value)
    lease = _lease(
        tenant_id=tenant_id,
        task_id=task.id,
        mission_id=mission_id,
        holder=holder,
        status=WorkerLeaseState.RELEASED.value,
    )
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    prior_receipt = _set_existing_run_admission(
        mission=mission, task=task, lease=lease, current_state=ExecutionTaskState.COMPLETED.value
    )
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=LocalQueueAdapter(),
        )

    assert result.run_admission_status == "completed"
    assert result.already_completed_task_ids == [str(task.id)]
    assert result.already_failed_task_ids == []
    assert result.run_receipts[0].executed_at == prior_receipt["executed_at"]
    dispatcher_cls.return_value.execute.assert_not_called()


def test_worker_run_admission_prior_failed_and_dead_lettered_receipts_remain_idempotent_without_dispatch() -> None:
    for terminal_state in (ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value):
        tenant_id = str(uuid.uuid4())
        mission_id = uuid.uuid4()
        holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
        task = _task(tenant_id=tenant_id, mission_id=mission_id, status=terminal_state)
        lease = _lease(
            tenant_id=tenant_id,
            task_id=task.id,
            mission_id=mission_id,
            holder=holder,
            status=WorkerLeaseState.RELEASED.value,
        )
        task.metadata_json["worker_lease_id"] = str(lease.id)
        mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
        prior_receipt = _set_existing_run_admission(
            mission=mission, task=task, lease=lease, current_state=terminal_state
        )
        mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
            patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
        ):
            result = mission_module.worker_run_admission(
                mission_id=mission_id,
                request=_request(),
                tenant_id=uuid.UUID(tenant_id),
                db=MagicMock(),
                queue=LocalQueueAdapter(),
            )

        assert result.run_admission_status == "failed"
        assert result.already_completed_task_ids == []
        assert result.already_failed_task_ids == [str(task.id)]
        assert result.run_receipts[0].executed_at == prior_receipt["executed_at"]
        dispatcher_cls.return_value.execute.assert_not_called()


def test_worker_run_admission_rechecks_nonterminal_prior_receipt_and_blocks_on_current_live_state() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.CLAIMED.value)
    lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    _set_existing_run_admission(mission=mission, task=task, lease=lease, current_state=ExecutionTaskState.RUNNING.value)
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])
    queue = _queue_with_task(tenant_id, mission_id, task.id)

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=queue,
        )

    assert result.run_admission_status == "blocked"
    assert result.already_failed_task_ids == []
    assert result.blocked_task_ids == [str(task.id)]
    assert result.blockers[0]["code"] == "run_task_not_running"
    assert result.blockers[0]["state"] == ExecutionTaskState.CLAIMED.value
    dispatcher_cls.return_value.execute.assert_not_called()


def test_worker_run_admission_old_completed_receipt_does_not_skip_new_retry_attempt() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _task(tenant_id=tenant_id, mission_id=mission_id, retry_count=1)
    current_lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
    old_lease = _lease(
        tenant_id=tenant_id,
        task_id=task.id,
        mission_id=mission_id,
        holder=holder,
        status=WorkerLeaseState.RELEASED.value,
    )
    task.metadata_json["worker_lease_id"] = str(current_lease.id)
    task.started_at = "2026-05-13T00:10:00+00:00"
    mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[current_lease])
    old_receipt = _set_existing_run_admission(
        mission=mission,
        task=task,
        lease=old_lease,
        current_state=ExecutionTaskState.COMPLETED.value,
        started_from_admission_at="2026-05-13T00:00:00+00:00",
        retry_count=0,
    )
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [current_lease, old_lease])
    queue = _queue_with_task(tenant_id, mission_id, task.id)

    def _execute(*, task_id: uuid.UUID, lease_id: uuid.UUID) -> None:
        assert lease_id == current_lease.id
        assert queue.complete_task(tenant_id=tenant_id, task_id=task_id, worker_id=holder).ok
        task.status = ExecutionTaskState.COMPLETED.value
        current_lease.status = WorkerLeaseState.RELEASED.value

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
    ):
        dispatcher_cls.return_value.execute.side_effect = _execute
        result = mission_module.worker_run_admission(
            mission_id=mission_id,
            request=_request(),
            tenant_id=uuid.UUID(tenant_id),
            db=MagicMock(),
            queue=queue,
        )

    assert result.run_admission_status == "completed"
    assert result.already_completed_task_ids == []
    assert result.completed_task_ids == [str(task.id)]
    assert result.run_receipts[0].worker_lease_id == str(current_lease.id)
    assert result.run_receipts[0].retry_count == 1
    assert mission.metadata_json["worker_run_admission"]["historical_run_receipts"] == [old_receipt]
    dispatcher_cls.return_value.execute.assert_called_once_with(task_id=task.id, lease_id=current_lease.id)


def test_worker_run_admission_old_failed_or_dead_lettered_receipt_does_not_skip_new_retry_attempt() -> None:
    for old_terminal_state in (ExecutionTaskState.FAILED.value, ExecutionTaskState.DEAD_LETTERED.value):
        tenant_id = str(uuid.uuid4())
        mission_id = uuid.uuid4()
        holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
        task = _task(tenant_id=tenant_id, mission_id=mission_id, retry_count=2)
        current_lease = _lease(tenant_id=tenant_id, task_id=task.id, mission_id=mission_id, holder=holder)
        old_lease = _lease(
            tenant_id=tenant_id,
            task_id=task.id,
            mission_id=mission_id,
            holder=holder,
            status=WorkerLeaseState.RELEASED.value,
        )
        task.metadata_json["worker_lease_id"] = str(current_lease.id)
        task.started_at = "2026-05-13T00:20:00+00:00"
        mission = _mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[current_lease])
        old_receipt = _set_existing_run_admission(
            mission=mission,
            task=task,
            lease=old_lease,
            current_state=old_terminal_state,
            started_from_admission_at="2026-05-13T00:10:00+00:00",
            retry_count=1,
        )
        mission_repo, task_repo, lease_repo = _repos(mission, [task], [current_lease, old_lease])
        queue = _queue_with_task(tenant_id, mission_id, task.id)

        def _execute(
            *,
            task_id: uuid.UUID,
            lease_id: uuid.UUID,
            current_lease=current_lease,
            queue=queue,
            tenant_id=tenant_id,
            holder=holder,
            task=task,
        ) -> None:
            assert lease_id == current_lease.id
            assert queue.complete_task(tenant_id=tenant_id, task_id=task_id, worker_id=holder).ok
            task.status = ExecutionTaskState.COMPLETED.value
            current_lease.status = WorkerLeaseState.RELEASED.value

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
            patch("backend.api.routes.mission.TaskDispatcher") as dispatcher_cls,
        ):
            dispatcher_cls.return_value.execute.side_effect = _execute
            result = mission_module.worker_run_admission(
                mission_id=mission_id,
                request=_request(),
                tenant_id=uuid.UUID(tenant_id),
                db=MagicMock(),
                queue=queue,
            )

        assert result.run_admission_status == "completed"
        assert result.already_failed_task_ids == []
        assert result.completed_task_ids == [str(task.id)]
        assert result.run_receipts[0].worker_lease_id == str(current_lease.id)
        assert result.run_receipts[0].retry_count == 2
        assert mission.metadata_json["worker_run_admission"]["historical_run_receipts"] == [old_receipt]
        dispatcher_cls.return_value.execute.assert_called_once_with(task_id=task.id, lease_id=current_lease.id)
