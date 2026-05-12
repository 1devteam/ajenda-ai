from __future__ import annotations

import copy
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
    metadata_json: dict[str, object] = {
        "runtime_task_type": "echo",
        "graph_node_key": "collect-signals",
        "capability_reference": {"capability_id": str(uuid.uuid4()), "name": "crm_read", "version": "1.0.0"},
        "adapter_reference": {"adapter_id": str(uuid.uuid4())},
    }
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


def _read_eligibility(mission: SimpleNamespace, tasks: list[SimpleNamespace], tenant_uuid: uuid.UUID):
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=tasks))
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_worker_dispatch_eligibility(
            mission_id=mission.id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )
    return result, mission_repo


def _read_preview(mission: SimpleNamespace, tasks: list[SimpleNamespace], tenant_uuid: uuid.UUID):
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=tasks))
    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
    ):
        result = mission_module.read_mission_worker_claim_preview(
            mission_id=mission.id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )
    return result, mission_repo


def _codes(items: list[dict[str, object]]) -> set[str]:
    return {str(item["code"]) for item in items}


def test_worker_dispatch_eligibility_eligible_for_current_queued_admitted_dispatch_ready_task() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id])

    result, mission_repo = _read_eligibility(mission, [queued], tenant_uuid)

    assert result.eligibility_status == "eligible"
    assert result.eligible_task_ids == [str(queued.id)]
    assert result.ineligible_task_ids == []
    assert result.worker_dispatch_authority.read_only is True
    assert result.worker_dispatch_authority.claims_tasks is False
    assert result.worker_dispatch_authority.creates_worker_leases is False
    mission_repo.update_metadata.assert_not_called()


def test_worker_dispatch_eligibility_blocked_when_dispatch_readiness_blocks() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id], admission_status="blocked"
    )

    result, _ = _read_eligibility(mission, [queued], tenant_uuid)

    assert result.eligibility_status == "blocked"
    assert result.eligible_task_ids == []
    assert str(queued.id) in result.blocked_task_ids
    assert "worker_dispatch_readiness_blocked" in _codes(result.blockers)


def test_worker_dispatch_eligibility_blocked_when_queue_admission_missing_or_stale() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    missing_queue = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id], queue_admission=False
    )

    missing_result, _ = _read_eligibility(missing_queue, [queued], tenant_uuid)
    assert missing_result.eligibility_status == "blocked"
    assert "runtime_queue_admission_missing" in _codes(missing_result.blockers)

    stale = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id])
    stale.metadata_json["runtime_queue_admission"]["materialized_execution_task_ids"] = [str(uuid.uuid4())]
    stale.metadata_json["runtime_queue_admission"]["admitted_execution_task_ids"] = [str(uuid.uuid4())]

    stale_result, _ = _read_eligibility(stale, [queued], tenant_uuid)
    assert stale_result.eligibility_status == "blocked"
    assert "queue_admission_materialization_mismatch" in _codes(stale_result.blockers)


def test_worker_dispatch_eligibility_blocked_when_materialization_missing_or_stale() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    missing_materialization = _make_mission(
        tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id], materialization=False
    )

    missing_result, _ = _read_eligibility(missing_materialization, [queued], tenant_uuid)
    assert missing_result.eligibility_status == "blocked"
    assert "runtime_task_materialization_missing" in _codes(missing_result.blockers)

    stale = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id])
    stale.metadata_json["runtime_task_materialization"]["materialization_status"] = "superseded"

    stale_result, _ = _read_eligibility(stale, [queued], tenant_uuid)
    assert stale_result.eligibility_status == "blocked"
    assert "no_current_materialized_tasks" in _codes(stale_result.blockers)


def test_worker_dispatch_eligibility_partial_for_mixed_states() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    planned = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.PLANNED.value)
    cancelled = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.CANCELLED.value)
    failed = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.FAILED.value)
    running = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.RUNNING.value)
    tasks = [queued, planned, cancelled, failed, running]
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id for task in tasks])

    result, _ = _read_eligibility(mission, tasks, tenant_uuid)

    assert result.eligibility_status == "partial"
    assert result.eligible_task_ids == [str(queued.id)]
    assert set(result.ineligible_task_ids) == {str(task.id) for task in [planned, cancelled, failed, running]}
    assert str(cancelled.id) in result.skipped_task_ids
    assert {str(planned.id), str(failed.id), str(running.id)} <= set(result.blocked_task_ids)


def test_worker_dispatch_eligibility_excludes_claimed_running_recovering_blocked_states() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    tasks = [
        _make_task(tenant_id=tenant_id, mission_id=mission_id, status=state.value)
        for state in (
            ExecutionTaskState.CLAIMED,
            ExecutionTaskState.RUNNING,
            ExecutionTaskState.RECOVERING,
            ExecutionTaskState.BLOCKED,
        )
    ]
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id for task in tasks])

    result, _ = _read_eligibility(mission, tasks, tenant_uuid)

    assert result.eligibility_status == "blocked"
    assert result.eligible_task_ids == []
    assert set(result.blocked_task_ids) == {str(task.id) for task in tasks}
    assert "worker_task_not_queued" in _codes(result.blockers)


def test_worker_dispatch_eligibility_excludes_terminal_or_failed_states() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    tasks = [
        _make_task(tenant_id=tenant_id, mission_id=mission_id, status=state.value)
        for state in (
            ExecutionTaskState.COMPLETED,
            ExecutionTaskState.CANCELLED,
            ExecutionTaskState.FAILED,
            ExecutionTaskState.DEAD_LETTERED,
        )
    ]
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id for task in tasks])

    result, _ = _read_eligibility(mission, tasks, tenant_uuid)

    assert result.eligibility_status == "blocked"
    assert result.eligible_task_ids == []
    assert {str(tasks[0].id), str(tasks[1].id)} <= set(result.skipped_task_ids)
    assert {str(tasks[2].id), str(tasks[3].id)} <= set(result.blocked_task_ids)


def test_worker_dispatch_eligibility_blocks_queued_task_missing_task_type() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    missing = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="missing")
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[missing.id])

    result, _ = _read_eligibility(mission, [missing], tenant_uuid)

    assert result.eligibility_status == "blocked"
    assert result.eligible_task_ids == []
    assert str(missing.id) in result.blocked_task_ids
    assert "worker_task_missing_task_type" in _codes(result.blockers)


def test_worker_dispatch_eligibility_blocks_task_missing_from_queue_admission_lists_or_dispatch_ready() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    admitted = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    not_admitted = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    not_materialized_in_queue = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    missing_task_type = _make_task(tenant_id=tenant_id, mission_id=mission_id, task_type="missing")
    tasks = [admitted, not_admitted, not_materialized_in_queue, missing_task_type]
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[task.id for task in tasks])
    mission.metadata_json["runtime_queue_admission"]["admitted_execution_task_ids"] = [
        str(admitted.id),
        str(not_materialized_in_queue.id),
        str(missing_task_type.id),
    ]
    mission.metadata_json["runtime_queue_admission"]["materialized_execution_task_ids"] = [
        str(admitted.id),
        str(not_admitted.id),
        str(missing_task_type.id),
    ]

    result, _ = _read_eligibility(mission, tasks, tenant_uuid)

    assert result.eligibility_status == "blocked"
    assert result.eligible_task_ids == []
    codes = _codes(result.blockers)
    assert "worker_dispatch_readiness_blocked" in codes
    assert "worker_task_not_queue_admitted" in codes
    assert "worker_task_not_queue_materialized" in codes
    assert "worker_task_not_dispatch_ready" in codes


def test_worker_dispatch_eligibility_hides_cross_tenant_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=None))

    with patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo):
        response = client.get(f"/v1/missions/{mission_id}/worker-dispatch-eligibility")

    assert response.status_code == 404


def test_worker_claim_preview_returns_envelope_per_eligible_task_with_claim_contract() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id])

    result, _ = _read_preview(mission, [queued], tenant_uuid)

    assert result.preview_status == "ready"
    assert len(result.claim_preview_envelopes) == 1
    envelope = result.claim_preview_envelopes[0]
    assert envelope.task_id == str(queued.id)
    assert envelope.current_task_state == "queued"
    assert envelope.expected_claim_from_state == "queued"
    assert envelope.future_claim_state == "claimed"
    assert envelope.worker_lease_required is True
    assert envelope.lease_scope == {"tenant_id": tenant_id, "mission_id": str(mission_id), "task_id": str(queued.id)}
    assert envelope.runtime_contract["requires_worker_lease"] is True
    assert envelope.runtime_contract["requires_state_machine_transition"] is True
    assert envelope.runtime_contract["requires_queue_claim"] is True
    assert envelope.runtime_contract["requires_heartbeat"] is True
    assert envelope.runtime_contract["requires_audit_event"] is True
    assert envelope.runtime_contract["requires_lineage_or_evidence_capture"] is True
    assert (
        envelope.source_references["materialization_reference"] == mission.metadata_json["runtime_task_materialization"]
    )
    assert envelope.source_references["queue_admission_reference"] == mission.metadata_json["runtime_queue_admission"]
    assert envelope.task_metadata_summary["task_type"] == "echo"
    assert envelope.task_metadata_summary["capability_reference"] == queued.metadata_json["capability_reference"]
    assert envelope.task_metadata_summary["adapter_reference"] == queued.metadata_json["adapter_reference"]
    assert envelope.task_metadata_summary["graph_node_key"] == "collect-signals"
    assert envelope.preview_only is True


def test_worker_claim_preview_excludes_blocked_tasks_and_reports_blocked_or_partial_status() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    running = _make_task(tenant_id=tenant_id, mission_id=mission_id, status=ExecutionTaskState.RUNNING.value)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id, running.id])

    partial_result, _ = _read_preview(mission, [queued, running], tenant_uuid)

    assert partial_result.preview_status == "partial"
    assert [envelope.task_id for envelope in partial_result.claim_preview_envelopes] == [str(queued.id)]
    assert str(running.id) in partial_result.blocked_task_ids

    blocked_mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[running.id])
    blocked_result, _ = _read_preview(blocked_mission, [running], tenant_uuid)

    assert blocked_result.preview_status == "blocked"
    assert blocked_result.claim_preview_envelopes == []
    assert str(running.id) in blocked_result.blocked_task_ids


def test_worker_claim_preview_is_read_only_and_does_not_mutate_runtime_or_call_execution_paths() -> None:
    tenant_id = str(uuid.uuid4())
    tenant_uuid = uuid.UUID(tenant_id)
    mission_id = uuid.uuid4()
    queued = _make_task(tenant_id=tenant_id, mission_id=mission_id)
    mission = _make_mission(tenant_id=tenant_id, mission_id=mission_id, task_ids=[queued.id])
    original_metadata = copy.deepcopy(mission.metadata_json)
    original_status = queued.status
    mission_repo = MagicMock(get_for_tenant=MagicMock(return_value=mission))
    task_repo = MagicMock(list_for_mission=MagicMock(return_value=[queued]))

    with (
        patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
        patch("backend.api.routes.mission.WorkerRuntimeService", create=True) as worker_runtime_cls,
        patch("backend.api.routes.mission.task_dispatcher", create=True) as dispatcher,
        patch("backend.api.routes.mission.WorkerLease", create=True) as worker_lease_cls,
        patch("backend.api.routes.mission.get_queue_adapter", create=True) as queue_adapter,
    ):
        result = mission_module.read_mission_worker_claim_preview(
            mission_id=mission_id, request=MagicMock(), tenant_id=tenant_uuid, db=MagicMock()
        )

    assert result.preview_status == "ready"
    assert mission.metadata_json == original_metadata
    assert queued.status == original_status
    mission_repo.update_metadata.assert_not_called()
    task_repo.update.assert_not_called()
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()
    worker_runtime_cls.assert_not_called()
    dispatcher.assert_not_called()
    worker_lease_cls.assert_not_called()
    queue_adapter.assert_not_called()
