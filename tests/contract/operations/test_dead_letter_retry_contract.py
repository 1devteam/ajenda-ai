from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes.operations import router
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.queue.base import QueueOperationResult
from backend.services.operations_service import OperationsService


class _RejectingOpsService:
    def retry_dead_letter(self, **_kwargs):
        raise ValueError("task is not dead-lettered or failed")


class _RecordingRetryOpsService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def retry_dead_letter(self, **kwargs):
        self.calls.append(kwargs)
        return {"task_id": str(kwargs["task_id"]), "status": "queued"}


def test_rg_dead_letter_retry_returns_400_on_non_retryable_task(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal("operator", str(tenant_id), PrincipalType.USER, roles=("operator",))
        return await call_next(request)

    app.include_router(router, prefix="/v1")

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
        lambda *_args, **_kwargs: _RejectingOpsService(),
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(f"/v1/operations/dead-letter/{uuid.uuid4()}/retry")

    assert response.status_code == 400
    assert "dead-lettered or failed" in str(response.json())


def test_rg_dead_letter_retry_route_passes_request_tenant_and_task_to_service(monkeypatch) -> None:
    app = FastAPI()
    tenant_id = uuid.uuid4()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal("operator", str(tenant_id), PrincipalType.USER, roles=("operator",))
        return await call_next(request)

    app.include_router(router, prefix="/v1")
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
    def __init__(self, task: ExecutionTask | None) -> None:
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
        self.recovered = False

    def list_dead_letter(self, *, tenant_id: str):
        return []

    def recover_task_for_retry(self, *, tenant_id: str, task_id: uuid.UUID, worker_id: str) -> QueueOperationResult:
        return QueueOperationResult(ok=False, reason="task not found in processing or pending queue")

    def enqueue_task(self, message):
        self.enqueued = True
        self.messages.append(message)
        return QueueOperationResult(ok=True)


def test_retry_dead_letter_contract_rejects_missing_task_for_tenant() -> None:
    tenant_id = str(uuid.uuid4())
    queue = _QueueStub()
    service = OperationsService(_SessionStub(None), queue)
    service._audit = MagicMock()

    with pytest.raises(ValueError, match="task not found for tenant"):
        service.retry_dead_letter(tenant_id=tenant_id, task_id=uuid.uuid4())

    assert queue.enqueued is False
    service._audit.append.assert_not_called()


def test_retry_dead_letter_contract_rejects_foreign_tenant_task_before_side_effects() -> None:
    tenant_id = str(uuid.uuid4())
    other_tenant_id = str(uuid.uuid4())
    task = ExecutionTask(
        tenant_id=other_tenant_id,
        mission_id=uuid.uuid4(),
        title="task",
        description="task",
        status=ExecutionTaskState.DEAD_LETTERED.value,
        metadata_json={},
    )
    queue = _QueueStub()
    service = OperationsService(_SessionStub(task), queue)
    service._audit = MagicMock()

    with pytest.raises(ValueError, match="task not found for tenant"):
        service.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

    assert queue.enqueued is False
    service._audit.append.assert_not_called()


def test_retry_dead_letter_contract_requeues_db_only_dead_lettered_task() -> None:
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
    service._audit = MagicMock()

    result = service.retry_dead_letter(tenant_id=tenant_id, task_id=task.id)

    assert result == {"task_id": str(task.id), "status": ExecutionTaskState.QUEUED.value}
    assert queue.enqueued is True
    assert session_flush_count(service) == 2
    service._audit.append.assert_called_once()


def session_flush_count(service: OperationsService) -> int:
    return getattr(service._session, "flush_count", 0)
