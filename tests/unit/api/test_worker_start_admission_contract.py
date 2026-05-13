from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import mission as mission_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState


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
    status: str = ExecutionTaskState.CLAIMED.value,
    task_type: object = "echo",
    worker_lease_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    metadata_json: dict[str, object] = {"runtime_task_type": "echo", "graph_node_key": "collect-signals"}
    if task_type != "missing":
        metadata_json["task_type"] = task_type
    if worker_lease_id is not None:
        metadata_json["worker_lease_id"] = str(worker_lease_id)
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        status=status,
        metadata_json=metadata_json,
    )


def _make_lease(
    *,
    tenant_id: str,
    task_id: uuid.UUID,
    holder_identity: str,
    status: str = WorkerLeaseState.CLAIMED.value,
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
    claim_status: str = "admitted",
) -> SimpleNamespace:
    claim_receipts = []
    for task in tasks:
        lease = next((candidate for candidate in leases or [] if candidate.task_id == task.id), None)
        claim_receipts.append(
            {
                "task_id": str(task.id),
                "tenant_id": tenant_id,
                "mission_id": str(mission_id),
                "previous_task_state": "queued",
                "current_task_state": "claimed",
                "worker_lease_id": str(lease.id) if lease is not None else None,
                "lease_scope": {"tenant_id": tenant_id, "mission_id": str(mission_id), "task_id": str(task.id)},
                "claim_source": "worker_claim_admission",
                "task_type": "echo",
                "claimed_at": "2026-05-12T00:00:00+00:00",
                "idempotency_status": "newly_claimed",
            }
        )
    return SimpleNamespace(
        id=mission_id,
        tenant_id=tenant_id,
        metadata_json={
            "runtime_task_materialization": {
                "schema_version": 1,
                "mission_id": str(mission_id),
                "tenant_id": tenant_id,
                "materialization_status": "materialized",
                "materialization_version": 1,
                "created_execution_task_ids": [str(task.id) for task in tasks],
            },
            "runtime_queue_admission": {
                "schema_version": 1,
                "mission_id": str(mission_id),
                "tenant_id": tenant_id,
                "admission_status": "admitted",
                "admitted_execution_task_ids": [str(task.id) for task in tasks],
            },
            "worker_claim_admission": {
                "schema_version": 1,
                "mission_id": str(mission_id),
                "tenant_id": tenant_id,
                "admission_status": claim_status,
                "admission_version": 1,
                "claimed_task_ids": [str(task.id) for task in tasks],
                "already_claimed_task_ids": [],
                "skipped_task_ids": [],
                "blocked_task_ids": [],
                "claim_receipts": claim_receipts,
                "blockers": [],
                "warnings": [],
                "materialization_reference": {"metadata_key": "runtime_task_materialization"},
                "queue_admission_reference": {"metadata_key": "runtime_queue_admission"},
                "dispatch_readiness_summary": {"readiness_status": "ready"},
                "worker_dispatch_eligibility_summary": {"preview_status": "ready"},
                "worker_claim_preview_reference": {"preview_status": "ready"},
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
    leases_by_id = {lease.id: lease for lease in leases}
    lease_repo = MagicMock()
    lease_repo.get.side_effect = lambda lease_id: leases_by_id.get(lease_id)
    lease_repo.list_for_task.side_effect = lambda task_id: [lease for lease in leases if lease.task_id == task_id]
    return mission_repo, task_repo, lease_repo


def test_worker_start_admission_starts_claimed_task_and_persists_receipt() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.start_admission_status == "admitted"
    assert result.started_task_ids == [str(task.id)]
    assert result.start_receipts[0].previous_task_state == "claimed"
    assert result.start_receipts[0].current_task_state == "running"
    assert result.start_receipts[0].idempotency_status == "newly_started"
    assert result.worker_start_authority.starts_execution is True
    assert result.worker_start_authority.executes_handlers is False
    assert task.status == ExecutionTaskState.RUNNING.value
    assert lease.status == WorkerLeaseState.ACTIVE.value
    assert lease.heartbeat_at is not None
    assert mission.metadata_json["worker_start_admission"]["start_receipts"][0]["task_id"] == str(task.id)


def test_worker_start_admission_is_idempotent_and_blocks_different_running_owner() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        first = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
        second = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
        third = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert first.started_task_ids == [str(task.id)]
    assert second.started_task_ids == [str(task.id)]
    assert third.started_task_ids == [str(task.id)]
    assert second.already_started_task_ids == [str(task.id)]
    assert third.already_started_task_ids == [str(task.id)]
    assert second.start_receipts[0].idempotency_status == "already_started_by_current_admission"
    assert third.start_admission_status == "admitted"
    assert len(mission.metadata_json["worker_start_admission"]["start_receipts"]) == 1

    other_lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(other_lease.id)
    mission.metadata_json["worker_claim_admission"]["claim_receipts"][0]["worker_lease_id"] = str(other_lease.id)
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [other_lease])
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        blocked = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert blocked.start_admission_status == "blocked"
    assert any(blocker["code"] == "task_running_without_current_start_admission" for blocker in blocked.blockers)


def test_worker_start_admission_blocks_missing_claim_stale_receipt_lease_task_type_and_bad_states() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    missing_claim_mission = SimpleNamespace(id=mission_id, tenant_id=tenant_id, metadata_json={})
    mission_repo, task_repo, lease_repo = _repos(missing_claim_mission, [task], [])
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        missing = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
    assert missing.start_admission_status == "blocked"
    assert any(blocker["code"] == "worker_claim_admission_missing" for blocker in missing.blockers)

    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    valid = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    no_type = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="missing")
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.QUEUED.value)
    missing_lease = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    foreign_lease_task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    valid_lease = _make_lease(tenant_id=tenant_id, task_id=valid.id, holder_identity=holder)
    no_type_lease = _make_lease(tenant_id=tenant_id, task_id=no_type.id, holder_identity=holder)
    queued_lease = _make_lease(tenant_id=tenant_id, task_id=queued.id, holder_identity=holder)
    foreign_lease = _make_lease(tenant_id="foreign", task_id=foreign_lease_task.id, holder_identity=holder)
    for task_item, lease in [
        (valid, valid_lease),
        (no_type, no_type_lease),
        (queued, queued_lease),
        (foreign_lease_task, foreign_lease),
    ]:
        task_item.metadata_json["worker_lease_id"] = str(lease.id)
    stale_mission = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, tasks=[valid], leases=[valid_lease], claim_status="blocked"
    )
    stale_repo, stale_task_repo, stale_lease_repo = _repos(stale_mission, [valid], [valid_lease])
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=stale_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=stale_task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=stale_lease_repo),
    ):
        stale = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
    assert stale.start_admission_status == "blocked"
    assert any(blocker["code"] == "worker_claim_admission_not_admitted" for blocker in stale.blockers)
    assert valid.status == ExecutionTaskState.CLAIMED.value

    mission = _make_mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        tasks=[valid, no_type, queued, missing_lease, foreign_lease_task],
        leases=[valid_lease, no_type_lease, queued_lease, foreign_lease],
    )
    mission.metadata_json["worker_claim_admission"]["claim_receipts"] = [
        receipt
        for receipt in mission.metadata_json["worker_claim_admission"]["claim_receipts"]
        if receipt["task_id"] != str(valid.id)
    ]
    mission_repo, task_repo, lease_repo = _repos(
        mission,
        [valid, no_type, queued, missing_lease, foreign_lease_task],
        [valid_lease, no_type_lease, queued_lease, foreign_lease],
    )
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    codes = {blocker["code"] for blocker in result.blockers}
    assert result.start_admission_status == "blocked"
    assert "worker_claim_receipt_missing" in codes
    assert "start_task_missing_task_type" in codes
    assert "worker_lease_id_missing" in codes
    assert "worker_lease_scope_mismatch" in codes
    assert "start_task_not_claimed" in codes
    assert queued.status == ExecutionTaskState.QUEUED.value


def test_worker_start_admission_returns_partial_without_losing_failed_claim_lease() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    first = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    second = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    first_lease = _make_lease(tenant_id=tenant_id, task_id=first.id, holder_identity=holder)
    second_lease = _make_lease(tenant_id=tenant_id, task_id=second.id, holder_identity=holder)
    first.metadata_json["worker_lease_id"] = str(first_lease.id)
    second.metadata_json["worker_lease_id"] = str(second_lease.id)
    mission = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, tasks=[first, second], leases=[first_lease, second_lease]
    )
    mission_repo, task_repo, lease_repo = _repos(mission, [first, second], [first_lease, second_lease])

    flush_count = 0

    def _flush() -> None:
        nonlocal flush_count
        flush_count += 1
        if flush_count == 2:
            raise ValueError("start write failed")

    db = MagicMock()
    db.flush.side_effect = _flush
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=db
        )

    assert result.start_admission_status == "partially_admitted"
    assert len(result.started_task_ids) == 1
    assert len(result.blocked_task_ids) == 1
    assert set(result.started_task_ids + result.blocked_task_ids) == {str(first.id), str(second.id)}
    failed_task = first if str(first.id) in result.blocked_task_ids else second
    failed_lease = first_lease if failed_task is first else second_lease
    assert failed_task.status == ExecutionTaskState.CLAIMED.value
    assert failed_lease.holder_identity == holder
    assert mission.metadata_json["worker_start_admission"]["started_task_ids"] == result.started_task_ids


def test_worker_start_admission_negative_authority_does_not_call_execution_paths() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    original_contracts = copy.deepcopy(
        {key: value for key, value in mission.metadata_json.items() if key != "worker_start_admission"}
    )
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.task_dispatcher", create=True) as dispatcher,
    ):
        result = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.worker_start_authority.creates_worker_leases is False
    assert result.worker_start_authority.claims_tasks is False
    assert result.worker_start_authority.dispatches_workers is False
    assert result.worker_start_authority.executes_handlers is False
    assert result.worker_start_authority.enqueues_work is False
    assert {key: mission.metadata_json[key] for key in original_contracts} == original_contracts
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher.assert_not_called()


def test_worker_start_admission_get_returns_latest_metadata_and_missing_is_read_only_blocked() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[])
    admission = {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": "admitted",
        "admission_version": 1,
        "started_task_ids": [str(uuid.uuid4())],
        "already_started_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "start_receipts": [],
        "blockers": [],
        "warnings": [],
        "runtime_authority": {"starts_execution": True, "read_only": False},
        "updated_at": "2026-05-12T00:00:00+00:00",
    }
    mission.metadata_json["worker_start_admission"] = admission
    mission_repo, _, _ = _repos(mission, [], [])

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        result = mission_module.read_mission_worker_start_admission(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.start_admission_status == "admitted"
    assert result.worker_start_authority.read_only is True
    assert result.worker_start_authority.starts_execution is False
    mission_repo.update_metadata.assert_not_called()

    missing = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[])
    missing_repo = MagicMock(get_for_tenant=MagicMock(return_value=missing))
    with patch("backend.api.routes.mission.MissionRepository", return_value=missing_repo):
        missing_result = mission_module.read_mission_worker_start_admission(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert missing_result.start_admission_status == "blocked"
    assert missing_result.worker_start_authority.read_only is True
    assert missing_result.blockers[0]["code"] == "worker_start_admission_missing"
    missing_repo.update_metadata.assert_not_called()


def test_worker_start_admission_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock(lock_for_tenant=MagicMock(return_value=None))

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/worker-start-admission")

    assert response.status_code == 404


def test_worker_start_admission_stays_idempotent_after_claim_retry() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    holder = f"worker_claim_admission:{tenant_id}:{mission_id}"
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity=holder)
    task.metadata_json["worker_lease_id"] = str(lease.id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, tasks=[task], leases=[lease])
    mission_repo, task_repo, lease_repo = _repos(mission, [task], [lease])

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.task_dispatcher", create=True) as dispatcher,
    ):
        first_start = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
        claim_retry = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
        second_start = mission_module.worker_start_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert first_start.start_admission_status == "admitted"
    assert claim_retry.claim_admission_status == "admitted"
    assert second_start.start_admission_status == "admitted"
    assert claim_retry.claimed_task_ids == [str(task.id)]
    assert claim_retry.already_claimed_task_ids == [str(task.id)]
    assert second_start.started_task_ids == [str(task.id)]
    assert second_start.already_started_task_ids == [str(task.id)]
    assert task.status == ExecutionTaskState.RUNNING.value
    assert lease.status == WorkerLeaseState.ACTIVE.value
    assert second_start.start_receipts[0].worker_lease_id == first_start.start_receipts[0].worker_lease_id
    assert second_start.start_receipts[0].started_at == first_start.start_receipts[0].started_at
    assert mission.metadata_json["worker_claim_admission"]["admission_status"] == "admitted"
    assert mission.metadata_json["worker_start_admission"]["admission_status"] == "admitted"
    assert mission.metadata_json["worker_claim_admission"]["claimed_task_ids"] == [str(task.id)]
    assert mission.metadata_json["worker_start_admission"]["started_task_ids"] == [str(task.id)]
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    dispatcher.assert_not_called()
