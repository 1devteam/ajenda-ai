"""Contract: ability-runtime queues via ExecutionCoordinator; worker dispatches tool.invoke."""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import ability_runtime as ability_runtime_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import ExecutionTaskState
from backend.services.execution_coordinator import CoordinationResult

REPO_ROOT = Path(__file__).resolve().parents[3]


def _ability_runtime_source() -> str:
    return (REPO_ROOT / "backend/api/routes/ability_runtime.py").read_text(encoding="utf-8")


def test_ability_runtime_launch_task_queues_through_execution_coordinator() -> None:
    tree = ast.parse(_ability_runtime_source())
    launch_fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "launch_task")
    source_segment = ast.get_source_segment(_ability_runtime_source(), launch_fn) or ""
    assert "ExecutionCoordinator" in source_segment
    assert ".queue_task(" in source_segment
    assert "TaskDispatcher" not in source_segment


def test_ability_runtime_does_not_import_task_dispatcher() -> None:
    assert "TaskDispatcher" not in _ability_runtime_source()


def test_task_dispatcher_registers_tool_invoke_handler() -> None:
    from backend.workers import handlers as _registered_handlers  # noqa: F401
    from backend.workers.task_dispatcher import _HANDLER_REGISTRY

    assert "tool.invoke" in _HANDLER_REGISTRY


def _build_ability_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(ability_runtime_module.router, prefix="/v1")

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


def test_ability_runtime_launch_returns_queued_contract() -> None:
    tenant_id = uuid.uuid4()
    app = _build_ability_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = MagicMock()
    task.id = task_id
    task.status = ExecutionTaskState.QUEUED.value

    quota = MagicMock()
    coordinator = MagicMock()
    coordinator.queue_task.return_value = CoordinationResult(
        ok=True,
        task_id=task_id,
        state=ExecutionTaskState.QUEUED.value,
        reason=None,
    )

    with (
        patch.object(ability_runtime_module, "QuotaEnforcementService", return_value=quota),
        patch.object(ability_runtime_module, "ExecutionCoordinator", return_value=coordinator),
        patch.object(ability_runtime_module, "Mission") as mission_cls,
        patch.object(ability_runtime_module, "ExecutionTask", return_value=task),
        patch.object(ability_runtime_module, "_ensure_runtime_authority", return_value=(None, None)),
    ):
        mission = MagicMock()
        mission.id = mission_id
        mission_cls.return_value = mission

        response = client.post(
            "/v1/ability-runtime/tasks",
            json={"action": "sales.research", "input": {"query": "acme"}},
            headers={"X-Tenant-Id": str(tenant_id), "X-Api-Key": "test-key"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["queue_status"] == "queued"
    assert payload["action"] == "sales.research"
    coordinator.queue_task.assert_called_once()


def test_worker_loop_entrypoint_uses_task_dispatcher_not_route_admission() -> None:
    worker_loop_source = inspect.getsource(
        __import__("backend.workers.worker_loop", fromlist=["WorkerLoop"]).WorkerLoop
    )
    assert "TaskDispatcher" in worker_loop_source
    assert "worker_run_admission" not in worker_loop_source.lower()
