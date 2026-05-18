from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.routes.admin import router as admin_router
from backend.app.dependencies.db import get_db_session
from backend.middleware.tenant_context import TenantContextMiddleware
from backend.services.tenant_lifecycle import TenantProvisionResult


class PrincipalMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, roles: tuple[str, ...] = ("admin",)) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._roles = roles

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = SimpleNamespace(
            subject_id="admin-1",
            roles=self._roles,
        )
        return await call_next(request)


def _app(*, roles: tuple[str, ...] = ("admin",)) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db_session] = lambda: MagicMock()
    app.include_router(admin_router, prefix="/v1")
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(PrincipalMiddleware, roles=roles)
    return app


def test_admin_provision_tenant_does_not_require_tenant_header() -> None:
    tenant_id = uuid.uuid4()

    with patch("backend.api.routes.admin.TenantLifecycleService") as service_cls:
        service = MagicMock()
        service.provision.return_value = TenantProvisionResult(
            tenant_id=tenant_id,
            slug="tenant-a",
            plan="starter",
            status="active",
        )
        service_cls.return_value = service

        response = TestClient(_app()).post(
            "/v1/admin/tenants",
            json={"name": "Tenant A", "slug": "tenant-a", "plan": "starter"},
        )

    assert response.status_code == 201
    assert response.json() == {
        "tenant_id": str(tenant_id),
        "slug": "tenant-a",
        "plan": "starter",
        "status": "active",
    }
    service.provision.assert_called_once_with(
        name="Tenant A",
        slug="tenant-a",
        plan="starter",
        actor="admin-1",
    )


def test_admin_routes_reject_non_admin_principal() -> None:
    response = TestClient(_app(roles=("tenant_admin",))).post(
        "/v1/admin/tenants",
        json={"name": "Tenant A", "slug": "tenant-a", "plan": "free"},
    )

    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_admin_suspend_maps_missing_tenant_to_404() -> None:
    tenant_id = uuid.uuid4()

    with patch("backend.api.routes.admin.TenantLifecycleService") as service_cls:
        from backend.repositories.tenant_repository import TenantNotFoundError

        service = MagicMock()
        service.suspend.side_effect = TenantNotFoundError("missing")
        service_cls.return_value = service

        response = TestClient(_app()).post(
            f"/v1/admin/tenants/{tenant_id}/suspend",
            json={"reason": "billing issue"},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "missing"


def test_admin_quota_status_response_shape() -> None:
    tenant_id = uuid.uuid4()
    status = SimpleNamespace(
        tenant_id=str(tenant_id),
        plan="starter",
        billing_period="2026-05-01",
        missions_created=1,
        missions_limit=25,
        tasks_created=2,
        tasks_limit=500,
        agents_provisioned=3,
        api_calls_count=4,
        api_calls_limit=25_000,
    )

    with patch("backend.api.routes.admin.QuotaEnforcementService") as service_cls:
        service = MagicMock()
        service.get_quota_status.return_value = status
        service_cls.return_value = service

        response = TestClient(_app()).get(f"/v1/admin/tenants/{tenant_id}/quota")

    assert response.status_code == 200
    assert response.json()["tenant_id"] == str(tenant_id)
    assert response.json()["usage"]["tasks_limit"] == 500
