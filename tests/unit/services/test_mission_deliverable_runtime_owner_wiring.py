from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import backend.services.worker_runtime_service as worker_runtime_module
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.queue.base import QueueOperationResult
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.worker_runtime_service import WorkerRuntimeService, _materialized_artifact_reference


def test_composition_owners_persist_canonical_deliverable_runtime_state() -> None:
    confirm_source = inspect.getsource(MissionCompositionService.confirm)
    recompile_source = inspect.getsource(MissionCompositionService.compile_for_mission)
    canonical_builder = "build_deliverable_runtime_state("

    assert canonical_builder in confirm_source
    assert "DELIVERABLE_RUNTIME_STATE_METADATA_KEY" in confirm_source
    assert canonical_builder in recompile_source
    assert "minimum_rows=record.intent.requested_quantity or 0" in confirm_source
    assert "minimum_rows=record.intent.requested_quantity or 0" in recompile_source
    assert "DELIVERABLE_RUNTIME_STATE_METADATA_KEY" in recompile_source
    assert "extract_deliverable_request" not in confirm_source
    assert "extract_deliverable_request" not in recompile_source


def test_worker_complete_refreshes_read_model_before_rollup_and_commit() -> None:
    source = inspect.getsource(WorkerRuntimeService.complete)

    refresh_index = source.index("self._refresh_deliverable_completion_read_model(task=task)")
    rollup_index = source.index("self._maybe_rollup_mission_status(task=task, worker_id=worker_id)")
    commit_index = source.index("self._session.commit()")

    assert refresh_index < rollup_index < commit_index


def test_completed_declared_artifact_gets_evidence_backed_identity() -> None:
    task = SimpleNamespace(
        metadata_json={"expected_output_contract": {"artifact": "web_page_observation"}},
    )

    assert _materialized_artifact_reference(task, ["evidence-1"]) == [
        {
            "artifact_id": "evidence-1",
            "artifact_key": "web_page_observation",
            "evidence_id": "evidence-1",
        }
    ]
    assert _materialized_artifact_reference(task, []) == []


def test_declared_artifact_validation_preserves_handler_error() -> None:
    task = SimpleNamespace(
        metadata_json={"expected_output_contract": {"artifact": "web_page_observation"}},
        status=ExecutionTaskState.RUNNING.value,
    )
    try:
        worker_runtime_module._validate_declared_output_contract(
            task,
            {
                "output": {
                    "web_page_observation": {
                        "error": "selector did not match any page element",
                    }
                }
            },
        )
    except ValueError as exc:
        assert "handler reported failure" in str(exc)
        assert "selector did not match" in str(exc)
    else:
        raise AssertionError("invalid browser artifact must fail closed")


def test_deliverable_read_model_failure_does_not_block_task_completion(monkeypatch) -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    service = WorkerRuntimeService(session, queue)

    tenant_id = "tenant-runtime-read-model"
    worker_id = "worker-runtime-read-model"
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    lease_id = uuid.uuid4()
    lease = SimpleNamespace(
        id=lease_id,
        tenant_id=tenant_id,
        task_id=task_id,
        holder_identity=worker_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=None,
    )
    task = SimpleNamespace(
        id=task_id,
        tenant_id=tenant_id,
        mission_id=mission_id,
        fleet_id=None,
        branch_id=None,
        status=ExecutionTaskState.RUNNING.value,
        metadata_json={"worker_lease_id": str(lease_id)},
    )
    mission = SimpleNamespace(metadata_json={})

    service._leases = MagicMock()
    service._leases.get.return_value = lease
    service._tasks = MagicMock()
    service._tasks.get.return_value = task
    service._tasks.list_for_mission.return_value = [task]
    service._audit = MagicMock()
    service._maybe_rollup_mission_status = MagicMock()

    class MissionRepoStub:
        def __init__(self, _session) -> None:
            pass

        def get_for_tenant(self, *, mission_id, tenant_id):
            return mission

    def _raise_refresh(*_args, **_kwargs):
        raise RuntimeError("read-model refresh failed")

    monkeypatch.setattr(worker_runtime_module, "MissionRepository", MissionRepoStub)
    monkeypatch.setattr("backend.services.worker_runtime_rollup.refresh_deliverable_completion_metadata", _raise_refresh)

    completed = service.complete(
        tenant_id=tenant_id,
        lease_id=lease_id,
        worker_id=worker_id,
    )

    assert completed is task
    assert task.status == ExecutionTaskState.COMPLETED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    session.commit.assert_called_once()
    queue.complete_task.assert_called_once_with(
        tenant_id=tenant_id,
        task_id=task_id,
        worker_id=worker_id,
    )
