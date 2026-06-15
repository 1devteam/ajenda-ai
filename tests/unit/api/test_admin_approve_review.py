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

# ---------------------------------------------------------------------------
# App factory — injects admin principal and overrides DB dependency
# ---------------------------------------------------------------------------


def _build_admin_app(*, is_admin: bool = True) -> tuple[FastAPI, MagicMock]:
    """Return (app, mock_db_session) with principal and DB wired."""
    mock_db = MagicMock()

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

    app.dependency_overrides[get_db_session] = _override_db
    return app, mock_db


# ---------------------------------------------------------------------------
# GET /v1/admin/tenants/{tenant_id}
# ---------------------------------------------------------------------------


class TestGetTenant:
    def test_returns_403_without_admin_role(self) -> None:
        app, _ = _build_admin_app(is_admin=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/v1/admin/tenants/{uuid.uuid4()}")
        assert resp.status_code == 403

    def test_returns_404_when_tenant_not_found(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        with patch("backend.repositories.tenant_repository.TenantRepository.get", return_value=None):
            resp = client.get(f"/v1/admin/tenants/{tid}")
        assert resp.status_code == 404

    def test_returns_tenant_detail_when_found(self) -> None:
        app, mock_db = _build_admin_app()
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
        app, mock_db = _build_admin_app()
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
        app, _ = _build_admin_app(is_admin=False)
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(f"/v1/admin/tenants/{uuid.uuid4()}/tasks/{uuid.uuid4()}/approve-review")
        assert resp.status_code == 403

    def test_returns_404_when_task_not_found(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=None,
        ):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 404

    def test_returns_404_when_task_belongs_to_different_tenant(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        other_tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(other_tid),
            status="pending_review",
        )
        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=fake_task,
        ):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 404

    def test_returns_409_when_task_not_in_pending_review(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="queued",
        )
        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=fake_task,
        ):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 409
        assert "pending_review" in resp.json()["detail"]

    def test_transitions_task_to_queued_and_returns_200(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="pending_review",
        )

        def _fake_transition(task, target):  # type: ignore[no-untyped-def]
            task.status = target.value
            return task

        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=fake_task,
        ):
            with patch("backend.api.routes.admin.transition_task", side_effect=_fake_transition):
                resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == str(task_id)
        assert body["previous_status"] == "pending_review"
        assert body["status"] == "queued"

    def test_cancelled_task_cannot_be_approved(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="cancelled",
        )
        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=fake_task,
        ):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 409

    def test_completed_task_cannot_be_approved(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="completed",
        )
        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=fake_task,
        ):
            resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 409

    def test_response_contains_all_required_fields(self) -> None:
        app, mock_db = _build_admin_app()
        client = TestClient(app, raise_server_exceptions=False)
        tid = uuid.uuid4()
        task_id = uuid.uuid4()
        fake_task = SimpleNamespace(
            id=task_id,
            tenant_id=str(tid),
            status="pending_review",
        )

        def _fake_transition(task, target):  # type: ignore[no-untyped-def]
            task.status = target.value
            return task

        with patch(
            "backend.repositories.execution_task_repository.ExecutionTaskRepository.get",
            return_value=fake_task,
        ):
            with patch("backend.api.routes.admin.transition_task", side_effect=_fake_transition):
                resp = client.post(f"/v1/admin/tenants/{tid}/tasks/{task_id}/approve-review")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"task_id", "previous_status", "status"}
