"""Route-level tests for the /auth endpoints.

The /auth/me route reads request.state.principal which is set by
AuthContextMiddleware in production. In tests we inject the principal
directly via a lightweight middleware to avoid needing a real OIDC stack.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.auth import router
from backend.auth.principal import Principal


def _build_app_with_principal(tenant_id: str, subject_id: str = "user-1") -> TestClient:
    """Build a minimal app that injects a principal on request.state."""
    app = FastAPI()

    @app.middleware("http")
    async def inject_principal(request, call_next):
        p = MagicMock(spec=Principal)
        p.subject_id = subject_id
        p.tenant_id = tenant_id
        p.principal_type = MagicMock()
        p.principal_type.value = "user"
        p.roles = ["tenant_admin"]
        p.permissions = []
        p.email = None
        request.state.principal = p
        return await call_next(request)

    app.include_router(router)
    return TestClient(app)


def test_auth_route_returns_principal() -> None:
    """GET /auth/me returns the principal from request.state."""
    client = _build_app_with_principal(tenant_id="tenant-a", subject_id="user-1")
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"


def test_auth_route_missing_principal_returns_401() -> None:
    """GET /auth/me without a principal on request.state returns 401."""
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/auth/me")
    assert response.status_code == 401
