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


class _SessionStub:
    def __init__(self, task: ExecutionTask) -> None:
        self._task = task

    def get(self, _model, _task_id):
        return self._task

    def flush(self) -> None:
        return None


class _QueueStub:
    def __init__(self) -> None:
        self.enqueued = False

    def enqueue_task(self, _message):
        self.enqueued = True
        return MagicMock(ok=True)


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
