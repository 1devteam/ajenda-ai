from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import operations as operations_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.services.operations_service import OperationsService


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(operations_module.router, prefix="/v1")

    def _override_tenant_id():
        return tenant_id

    def _override_db():
        return MagicMock()

    def _override_queue():
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app


def test_dead_letter_inspection_contract_returns_service_payload() -> None:
    tenant_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    service.inspect_dead_letter.return_value = [
        {
            "task_id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "status": "dead_lettered",
        }
    ]

    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.get("/v1/operations/dead-letter")

    assert response.status_code == 200
    assert response.json() == service.inspect_dead_letter.return_value
    service.inspect_dead_letter.assert_called_once_with(tenant_id=str(tenant_id))


def test_dead_letter_retry_contract_returns_service_payload() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    service.retry_dead_letter.return_value = {
        "task_id": str(task_id),
        "status": "queued",
    }

    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.post(f"/v1/operations/dead-letter/{task_id}/retry")

    assert response.status_code == 200
    assert response.json() == {"task_id": str(task_id), "status": "queued"}
    service.retry_dead_letter.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_dead_letter_retry_contract_returns_400_on_illegal_retry() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    service = MagicMock()
    service.retry_dead_letter.side_effect = ValueError("task is not in dead-letter state")

    with patch("backend.api.routes.operations.OperationsService", return_value=service):
        response = client.post(f"/v1/operations/dead-letter/{task_id}/retry")

    assert response.status_code == 400
    assert response.json() == {"detail": "task is not in dead-letter state"}
    service.retry_dead_letter.assert_called_once_with(tenant_id=str(tenant_id), task_id=task_id)


def test_dead_letter_inspection_service_scopes_query_by_tenant_and_dead_lettered_status() -> None:
    tenant_id = str(uuid.uuid4())

    task = ExecutionTask(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="dead-lettered task",
        description="dead-lettered task",
        status=ExecutionTaskState.DEAD_LETTERED.value,
        metadata_json={},
    )

    session = MagicMock()
    session.scalars.return_value = [task]
    service = OperationsService(session, MagicMock())

    result = service.inspect_dead_letter(tenant_id=tenant_id)

    assert result == [
        {
            "task_id": str(task.id),
            "mission_id": str(task.mission_id),
            "status": ExecutionTaskState.DEAD_LETTERED.value,
        }
    ]

    stmt = session.scalars.call_args.args[0]
    compiled = str(stmt)
    params = stmt.compile().params
    assert "execution_tasks.tenant_id" in compiled
    assert "execution_tasks.status" in compiled
    assert params["tenant_id_1"] == tenant_id
    assert params["status_1"] == ExecutionTaskState.DEAD_LETTERED.value
