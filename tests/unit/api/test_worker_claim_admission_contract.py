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
    status: str = ExecutionTaskState.QUEUED.value,
    task_type: object = "echo",
) -> SimpleNamespace:
    metadata_json: dict[str, object] = {"runtime_task_type": "echo", "graph_node_key": "collect-signals"}
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
    *, tenant_id: str, mission_id: uuid.UUID, task_ids: list[uuid.UUID], queue_task_ids: list[uuid.UUID] | None = None
) -> SimpleNamespace:
    admitted_ids = task_ids if queue_task_ids is None else queue_task_ids
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
                "created_execution_task_ids": [str(task_id) for task_id in task_ids],
            },
            "runtime_queue_admission": {
                "schema_version": 1,
                "mission_id": str(mission_id),
                "tenant_id": tenant_id,
                "admission_status": "admitted",
                "materialized_execution_task_ids": [str(task_id) for task_id in task_ids],
                "admitted_execution_task_ids": [str(task_id) for task_id in admitted_ids],
            },
        },
    )


def _make_lease(*, tenant_id: str, task_id: uuid.UUID, holder_identity: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=task_id,
        holder_identity=holder_identity,
        status=WorkerLeaseState.CLAIMED.value,
    )


def _repos(
    mission: SimpleNamespace, tasks: list[SimpleNamespace], leases: dict[uuid.UUID, list[SimpleNamespace]] | None = None
):
    mission_repo = MagicMock()
    mission_repo.lock_for_tenant.return_value = mission
    mission_repo.get_for_tenant.return_value = mission

    def _update_metadata(*, mission: SimpleNamespace, metadata_json: dict[str, object]) -> SimpleNamespace:
        mission.metadata_json = metadata_json
        return mission

    mission_repo.update_metadata.side_effect = _update_metadata
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=tasks))
    lease_repo = MagicMock()
    lease_repo.list_for_task.side_effect = lambda task_id: list((leases or {}).get(task_id, []))

    def _add_lease(lease):
        if getattr(lease, "id", None) is None:
            lease.id = uuid.uuid4()
        (leases if leases is not None else {}).setdefault(lease.task_id, []).append(lease)
        return lease

    lease_repo.add.side_effect = _add_lease
    return mission_repo, task_repo, lease_repo


def test_worker_claim_admission_claims_preview_eligible_queued_task_and_persists_receipt() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id])
    leases: dict[uuid.UUID, list[SimpleNamespace]] = {}
    mission_repo, task_repo, lease_repo = _repos(mission, [task], leases)
    db = MagicMock()

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=db
        )

    assert result.claim_admission_status == "admitted"
    assert result.claimed_task_ids == [str(task.id)]
    assert result.claim_receipts[0].previous_task_state == "queued"
    assert result.claim_receipts[0].current_task_state == "claimed"
    assert result.claim_receipts[0].idempotency_status == "newly_claimed"
    assert result.worker_claim_authority.creates_worker_leases is True
    assert result.worker_claim_authority.starts_execution is False
    assert task.status == ExecutionTaskState.CLAIMED.value
    assert len(leases[task.id]) == 1
    persisted = mission.metadata_json["worker_claim_admission"]
    assert persisted["claim_receipts"][0]["task_id"] == str(task.id)
    assert task.metadata_json["worker_lease_id"] == str(leases[task.id][0].id)


def test_worker_claim_admission_is_idempotent_for_current_admission_and_does_not_duplicate_leases() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id])
    leases: dict[uuid.UUID, list[SimpleNamespace]] = {}
    mission_repo, task_repo, lease_repo = _repos(mission, [task], leases)

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        first = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
        second = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )
        third = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert first.claimed_task_ids == [str(task.id)]
    assert second.claimed_task_ids == [str(task.id)]
    assert third.claimed_task_ids == [str(task.id)]
    assert second.already_claimed_task_ids == [str(task.id)]
    assert third.already_claimed_task_ids == [str(task.id)]
    assert second.claim_receipts[0].idempotency_status == "already_claimed_by_current_admission"
    assert third.claim_receipts[0].idempotency_status == "already_claimed_by_current_admission"
    assert second.claim_admission_status == "admitted"
    assert third.claim_admission_status == "admitted"
    assert second.claim_receipts[0].worker_lease_id == first.claim_receipts[0].worker_lease_id
    assert third.claim_receipts[0].worker_lease_id == first.claim_receipts[0].worker_lease_id
    assert second.claim_receipts[0].claimed_at == first.claim_receipts[0].claimed_at
    assert third.claim_receipts[0].claimed_at == first.claim_receipts[0].claimed_at
    assert mission.metadata_json["worker_claim_admission"]["claimed_task_ids"] == [str(task.id)]
    assert len(leases[task.id]) == 1


def test_worker_claim_admission_blocks_task_claimed_by_different_active_lease() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.CLAIMED.value)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id])
    foreign_lease = _make_lease(tenant_id=tenant_id, task_id=task.id, holder_identity="worker:other")
    mission_repo, task_repo, lease_repo = _repos(mission, [task], {task.id: [foreign_lease]})

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.claim_admission_status == "blocked"
    assert result.claimed_task_ids == []
    assert str(task.id) in result.blocked_task_ids
    assert any(blocker["code"] == "task_claimed_by_different_active_lease" for blocker in result.blockers)


def test_worker_claim_admission_blocks_missing_preview_stale_queue_and_missing_task_type() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="missing")
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id], queue_task_ids=[])
    mission.metadata_json["runtime_queue_admission"]["materialized_execution_task_ids"] = [str(uuid.uuid4())]
    mission_repo, task_repo, lease_repo = _repos(mission, [task], {})

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    codes = {blocker["code"] for blocker in result.blockers}
    assert result.claim_admission_status == "blocked"
    assert result.claimed_task_ids == []
    assert "queue_admission_materialization_mismatch" in codes
    assert "worker_task_not_queue_admitted" in codes
    assert "worker_task_missing_task_type" in codes
    assert task.status == ExecutionTaskState.QUEUED.value


def test_worker_claim_admission_returns_partial_when_one_task_claim_fails_after_another_succeeds() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    first = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    second = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[first.id, second.id])
    leases: dict[uuid.UUID, list[SimpleNamespace]] = {}
    mission_repo, task_repo, lease_repo = _repos(mission, [first, second], leases)

    def _add_lease(lease):
        if lease.task_id == second.id:
            raise ValueError("lease write failed")
        leases.setdefault(lease.task_id, []).append(lease)
        return lease

    lease_repo.add.side_effect = _add_lease

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
    ):
        result = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.claim_admission_status == "partially_admitted"
    assert str(first.id) in result.claimed_task_ids
    assert str(second.id) in result.blocked_task_ids
    assert second.status == ExecutionTaskState.QUEUED.value
    assert mission.metadata_json["worker_claim_admission"]["claimed_task_ids"] == [str(first.id)]


def test_worker_claim_admission_negative_authority_does_not_call_execution_paths() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id])
    original_metadata = copy.deepcopy(mission.metadata_json)
    mission_repo, task_repo, lease_repo = _repos(mission, [task], {})

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.WorkerLeaseRepository", return_value=lease_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.WorkerRuntimeService", create=True) as worker_runtime_cls,
        patch("backend.api.routes.mission.task_dispatcher", create=True) as dispatcher,
    ):
        result = mission_module.worker_claim_admission(
            mission_id=mission_id, request=MagicMock(headers={}), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.worker_claim_authority.starts_execution is False
    assert result.worker_claim_authority.dispatches_workers is False
    assert result.worker_claim_authority.executes_handlers is False
    assert result.worker_claim_authority.enqueues_work is False
    assert mission.metadata_json != original_metadata
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    worker_runtime_cls.assert_not_called()
    dispatcher.assert_not_called()


def test_worker_claim_admission_get_returns_latest_metadata_and_missing_is_read_only_blocked() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    task = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id])
    admission = {
        "schema_version": 1,
        "mission_id": str(mission_id),
        "tenant_id": tenant_id,
        "admission_status": "admitted",
        "admission_version": 1,
        "claimed_task_ids": [str(task.id)],
        "already_claimed_task_ids": [],
        "skipped_task_ids": [],
        "blocked_task_ids": [],
        "claim_receipts": [],
        "blockers": [],
        "warnings": [],
        "runtime_authority": {"claims_tasks": True, "read_only": False, "preview_only": False},
        "updated_at": "2026-05-12T00:00:00+00:00",
    }
    mission.metadata_json["worker_claim_admission"] = admission
    mission_repo, _, _ = _repos(mission, [task], {})

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        result = mission_module.read_mission_worker_claim_admission(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.claim_admission_status == "admitted"
    assert result.claimed_task_ids == [str(task.id)]
    assert result.worker_claim_authority.read_only is True
    mission_repo.update_metadata.assert_not_called()

    missing = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[])
    missing_repo = MagicMock(get_for_tenant=MagicMock(return_value=missing))
    with patch("backend.api.routes.mission.MissionRepository", return_value=missing_repo):
        missing_result = mission_module.read_mission_worker_claim_admission(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert missing_result.claim_admission_status == "blocked"
    assert missing_result.worker_claim_authority.read_only is True
    assert missing_result.blockers[0]["code"] == "worker_claim_admission_missing"
    missing_repo.update_metadata.assert_not_called()


def test_worker_claim_admission_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock(lock_for_tenant=MagicMock(return_value=None))

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.post(f"/v1/missions/{mission_id}/worker-claim-admission")

    assert response.status_code == 404
