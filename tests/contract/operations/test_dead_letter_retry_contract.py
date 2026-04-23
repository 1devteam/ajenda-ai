from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.operations import router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.operations_service import OperationsService


class _RejectingOpsService:
    def retry_dead_letter(self, **_kwargs):
        raise ValueError("Invalid task transition: 'dead_lettered' -> 'queued'.")


class _RecordingRetryOpsService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def retry_dead_letter(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": str(kwargs["task_id"]), "status": "queued"}


def test_rg_dead_letter_retry_returns_400_on_illegal_transition(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    def _tenant_dep() -> uuid.UUID:
        return uuid.uuid4()

    def _db_dep():
        yield MagicMock()

    def _queue_dep():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _tenant_dep
    app.dependency_overrides[get_tenant_db_session] = _db_dep
    app.dependency_overrides[get_queue_adapter] = _queue_dep

    monkeypatch.setattr(
        "backend.api.routes.operations.OperationsService",
        lambda *_args, **_kwargs: _RejectingOpsService(),
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(f"/v1/operations/dead-letter/{uuid.uuid4()}/retry")

    assert response.status_code == 400
    assert "dead_lettered" in str(response.json())


def test_rg_dead_letter_retry_route_passes_request_tenant_and_task_to_service(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    service = _RecordingRetryOpsService()

    def _tenant_dep() -> uuid.UUID:
        return tenant_id

    def _db_dep():
        yield MagicMock()

    def _queue_dep():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _tenant_dep
    app.dependency_overrides[get_tenant_db_session] = _db_dep
    app.dependency_overrides[get_queue_adapter] = _queue_dep

    monkeypatch.setattr(
        "backend.api.routes.operations.OperationsService",
        lambda *_args, **_kwargs: service,
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(f"/v1/operations/dead-letter/{task_id}/retry")

    assert response.status_code == 200
    assert service.calls == [{"tenant_id": str(tenant_id), "task_id": task_id}]


class _SessionStub:
    def __init__(self, task: ExecutionTask) -> None:
        self._task = task
        self.flush_count = 0

    def get(self, _model, _task_id):
        return self._task

    def flush(self) -> None:
        self.flush_count += 1
        return None


class _QueueStub:
    def __init__(self) -> None:
        self.enqueued = False
        self.messages: list[object] = []

    def enqueue_task(self, message):
        self.enqueued = True
        self.messages.append(message)
        return MagicMock(ok=True)


class _FailingQueueStub:
    def __init__(self) -> None:
        self.enqueued = False
        self.messages: list[object] = []

    def enqueue_task(self, message):
        self.enqueued = True
        self.messages.append(message)
        return MagicMock(ok=False, reason="queue enqueue failed")


def test_retry_dead_letter_contract_rejects_illegal_dead_lettered_transition() -> None:
    tenant_id = str(uuid.uuid4())
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="task",
        description="task",
        status=ExecutionTaskState.DEAD_LETTERED.value,
        metadata_json={},
    )
    queue = _QueueStub()
    service = OperationsService(_SessionStub(task), queue)

    with pytest.raises(ValueError, match="Invalid task transition"):
        service.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

    assert queue.enqueued is False


def test_retry_dead_letter_contract_returns_queued_status_and_appends_audit_on_success() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=mission_id,
        title="task",
        description="task",
        status=ExecutionTaskState.DEAD_LETTERED.value,
        metadata_json={"hello": "world"},
    )
    session = _SessionStub(task)
    queue = _QueueStub()
    service = OperationsService(session, queue)
    service._audit = MagicMock()

    result = service.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

    assert queue.enqueued is True
    assert len(queue.messages) == 1
    message = queue.messages[0]
    assert message.tenant_id == tenant_id
    assert message.task_id == task.id
    assert message.mission_id == mission_id
    assert message.fleet_id == task.fleet_id
    assert message.branch_id == task.branch_id
    assert message.payload == {"hello": "world"}
    assert task.status == ExecutionTaskState.QUEUED.value
    assert session.flush_count == 2
    assert result == {"task_id": str(task.id), "status": ExecutionTaskState.QUEUED.value}
    service._audit.append.assert_called_once()
    audit_event = service._audit.append.call_args.args[0]
    assert audit_event.tenant_id == tenant_id
    assert audit_event.mission_id == mission_id
    assert audit_event.category == "operations"
    assert audit_event.action == "retry_dead_letter"
    assert audit_event.actor == "operations_service"
    assert audit_event.payload_json == {"task_id": str(task.id)}


def test_retry_dead_letter_contract_rolls_back_to_dead_lettered_when_enqueue_fails() -> None:
    tenant_id = str(uuid.uuid4())
    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="task",
        description="task",
        status=ExecutionTaskState.DEAD_LETTERED.value,
        metadata_json={},
    )
    session = _SessionStub(task)
    queue = _FailingQueueStub()
    service = OperationsService(session, queue)
    service._audit = MagicMock()

    with pytest.raises(ValueError, match="queue enqueue failed"):
        service.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

    assert queue.enqueued is True
    assert len(queue.messages) == 1
    assert task.status == ExecutionTaskState.DEAD_LETTERED.value
    assert session.flush_count == 2
    service._audit.append.assert_not_called()
