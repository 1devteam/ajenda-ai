"""Unit tests for admin approve-review and get-tenant endpoints.

Tests the two new endpoints added to backend/api/routes/admin.py:
  - GET  /v1/admin/tenants/{tenant_id}
  - POST /v1/admin/tenants/{tenant_id}/tasks/{task_id}/approve-review

Uses FastAPI dependency_overrides to avoid any real DB or infrastructure,
following the pattern established in tests/unit/api/test_capability_adapter_route.py.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import admin as admin_module
from backend.app.dependencies.db import get_db_session
from backend.app.dependencies.services import get_queue_adapter

# ---------------------------------------------------------------------------
# App factory — injects admin principal and overrides DB/queue dependencies
# ---------------------------------------------------------------------------


def _build_admin_app(*, is_admin: bool = True) -> tuple[FastAPI, MagicMock, MagicMock]:
    """Return (app, mock_db_session, mock_queue) with dependencies wired."""
    mock_db = MagicMock()
    mock_queue = MagicMock()

    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = SimpleNamespace(
            subject_id="admin-test",
            roles={"admin"} if is_admin else {"user"},
        )
        return await call_next(request)

    app.include_router(admin_module.router, prefix="/v1")

    def _override_db():  # type: ignore[no-untyped-def]
        yield mock_db

    def _override_queue():  # type: ignore[no-untyped-def]
        return mock_queue

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_queue_adapter] = _override_queue
    return app, mock_db, mock_queue


# ---------------------------------------------------------------------------
# GET /v1/admin/tenants/{tenant_id}
# ---------------------------------------------------------------------------


class TestGetTenant:
    def test_returns_403_without_admin_role(self) -> None:
        app, _, _ = _build_admin_app(is_admin=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/admin/tenants/{uuid.uuid4()}")
        assert resp.status_code == 403

    def test_returns_404_when_tenant_not_found(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        with patch("backend.repositories.tenant_repository.TenantRepository.get", return_value=None):
            resp = client.get(f"/v1/admin/tenants/{tid}")
        assert resp.status_code == 404

    def test_returns_tenant_detail_when_found(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        fake_tenant = SimpleNamespace(
            id=tid,
            name="Acme Corp",
            slug="acme",
            plan="pro",
            status="active",
            stripe_customer_id="cus_test123",
        )
        with patch(
            "backend.repositories.tenant_repository.TenantRepository.get",
            return_value=fake_tenant,
        ):
            resp = client.get(f"/v1/admin/tenants/{tid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tenant_id"] == str(tid)
        assert body["name"] == "Acme Corp"
        assert body["slug"] == "acme"
        assert body["plan"] == "pro"
        assert body["status"] == "active"
        assert body["stripe_customer_id"] == "cus_test123"

    def test_stripe_customer_id_may_be_null(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        fake_tenant = SimpleNamespace(
            id=tid,
            name="Free Tenant",
            slug="free-co",
            plan="free",
            status="active",
            stripe_customer_id=None,
        )
        with patch(
            "backend.repositories.tenant_repository.TenantRepository.get",
            return_value=fake_tenant,
        ):
            resp = client.get(f"/v1/admin/tenants/{tid}")
        assert resp.status_code == 200
        assert resp.json()["stripe_customer_id"] is None


# ---------------------------------------------------------------------------
# POST /v1/admin/tenants/{tenant_id}/tasks/{task_id}/approve-review
# ---------------------------------------------------------------------------


class TestApproveTaskReview:
    def test_returns_403_without_admin_role(self) -> None:
        app, _, _ = _build_admin_app(is_admin=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/v1/admin/tenants/{uuid.uuid4()}/tasks/{uuid.uuid4()}/approve-review")
        assert resp.status_code == 403

    def test_returns_404_when_task_not_found(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=None):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 404

    def test_returns_404_when_task_belongs_to_different_tenant(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        other_tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(other_tid),
            status="pending_review",
        )
        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 404

    def test_returns_409_when_task_not_in_pending_review(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="queued",
        )
        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 409
        assert "pending_review" in resp.json()["detail"]

    def test_approval_queues_through_execution_coordinator_and_returns_200(self) -> None:
        app, mock_db, mock_queue = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="pending_review",
        )
        result = SimpleNamespace(ok=True, task_id=task_id, state="queued")

        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            with patch("backend.api.routes.admin.ExecutionCoordinator") as coordinator_cls:
                coordinator = coordinator_cls.return_value
                coordinator.approve_review_and_queue.return_value = result
                resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")

        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == str(task_id)
        assert body["previous_status"] == "pending_review"
        assert body["status"] == "queued"
        coordinator_cls.assert_called_once_with(mock_db, mock_queue)
        coordinator.approve_review_and_queue.assert_called_once_with(
            tenant_id=str(tid),
            task_id=task_id,
            actor="admin-test",
        )
        mock_db.commit.assert_called_once_with()

    def test_queue_failure_rolls_back_and_returns_400(self) -> None:
        app, mock_db, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="pending_review",
        )

        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            with patch("backend.api.routes.admin.ExecutionCoordinator") as coordinator_cls:
                coordinator_cls.return_value.approve_review_and_queue.side_effect = ValueError("queue enqueue failed")
                resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")

        assert resp.status_code == 400
        assert "queue enqueue failed" in resp.json()["detail"]
        mock_db.rollback.assert_called_once_with()

    def test_cancelled_task_cannot_be_approved(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="cancelled",
        )
        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 409

    def test_completed_task_cannot_be_approved(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="completed",
        )
        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 409

    def test_response_contains_all_required_fields(self) -> None:
        app, _, _ = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="pending_review",
        )
        result = SimpleNamespace(ok=True, task_id=task_id, state="queued")

        with patch.object(admin_module.ExecutionTaskRepository, "get", return_value=fake_task):
            with patch("backend.api.routes.admin.ExecutionCoordinator") as coordinator_cls:
                coordinator_cls.return_value.approve_review_and_queue.return_value = result
                resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")

        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"task_id", "previous_status", "status"}
