from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import review_queue as review_queue_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
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

    app.include_router(review_queue_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = lambda: MagicMock()
    return app


def test_list_review_queue_returns_pending_items() -> None:
    tenant_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id))

    with patch("backend.api.routes.review_queue.list_review_queue") as mock_list:
        mock_list.return_value = [
            {
                "artifact_id": "pitch_email-1",
                "artifact_type": "pitch_email",
                "review_status": "pending",
                "content": {"to": "ops@example.com"},
                "metadata": {},
            }
        ]

        response = client.get("/v1/review-queue", params={"status": "pending"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["artifact_id"] == "pitch_email-1"


def test_approve_review_queue_item_runs_workflow_hook() -> None:
    tenant_id = uuid.uuid4()
    client = TestClient(_build_app(tenant_id))
    session = MagicMock()

    with (
        patch("backend.api.routes.review_queue.read_artifact") as mock_read,
        patch("backend.api.routes.review_queue.update_review_status") as mock_update,
        patch("backend.services.light_crm.workflow.on_draft_approved") as mock_hook,
    ):
        mock_read.return_value = {
            "artifact_id": "pitch_email-1",
            "artifact_type": "pitch_email",
            "review_status": "pending",
            "content": {"to": "ops@example.com", "subject": "Hello"},
        }
        mock_update.return_value = {
            "artifact_id": "pitch_email-1",
            "artifact_type": "pitch_email",
            "review_status": "approved",
            "content": {"to": "ops@example.com", "subject": "Hello"},
        }

        app = _build_app(tenant_id)
        app.dependency_overrides[get_tenant_db_session] = lambda: session
        client = TestClient(app)

        response = client.post("/v1/review-queue/pitch_email-1/approve", json={"note": "looks good"})

    assert response.status_code == 200
    mock_hook.assert_called_once()
    session.commit.assert_called_once()


def test_tenant_task_approval_uses_payload_bound_coordinator_path() -> None:
    tenant_id = uuid.uuid4()
    task_id = uuid.uuid4()
    session = MagicMock()
    queue = MagicMock()
    task = MagicMock(id=task_id, tenant_id=str(tenant_id), status="pending_review")
    result = MagicMock(state="queued")
    app = _build_app(tenant_id)
    app.dependency_overrides[get_tenant_db_session] = lambda: session
    app.dependency_overrides[get_queue_adapter] = lambda: queue

    with (
        patch.object(review_queue_module.ExecutionTaskRepository, "get_for_tenant", return_value=task),
        patch.object(review_queue_module, "require_route_permission"),
        patch.object(review_queue_module, "ExecutionCoordinator") as coordinator_cls,
    ):
        coordinator_cls.return_value.approve_review_and_queue.return_value = result
        response = TestClient(app).post(
            f"/v1/review-queue/tasks/{task_id}/approve",
            json={"approval_expires_at": "2099-01-01T00:00:00Z"},
        )

    assert response.status_code == 200
    coordinator_cls.return_value.approve_review_and_queue.assert_called_once()
    call = coordinator_cls.return_value.approve_review_and_queue.call_args.kwargs
    assert call["tenant_id"] == str(tenant_id)
    assert call["task_id"] == task_id
    assert call["actor"] == "test-user"
    assert call["approval_expires_at"].isoformat() == "2099-01-01T00:00:00+00:00"
    session.commit.assert_called_once()
