from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.middleware.tenant_context import TenantContextMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)

    @app.get("/health")
    def health(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    @app.get("/readiness")
    def readiness(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    @app.get("/metrics")
    def metrics(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    @app.get("/auth/status")
    def auth_status(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    @app.get("/api-keys")
    def api_keys(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    @app.get("/protected")
    def protected(request: Request) -> dict[str, str | None]:
        return {"tenant_id": getattr(request.state, "tenant_id", None)}

    return app


def test_public_probe_paths_do_not_require_tenant_header() -> None:
    client = TestClient(_app())

    for path in ("/health", "/readiness", "/metrics", "/auth/status"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.json()["tenant_id"] is None


def test_tenant_owned_paths_require_tenant_header() -> None:
    client = TestClient(_app())

    response = client.get("/protected")

    assert response.status_code == 400
    assert response.json()["detail"] == "X-Tenant-Id header required"


def test_api_keys_path_is_not_public_exempt() -> None:
    client = TestClient(_app())

    response = client.get("/api-keys")

    assert response.status_code == 400


def test_tenant_header_is_attached_to_request_state() -> None:
    client = TestClient(_app())

    response = client.get("/protected", headers={"X-Tenant-Id": "tenant-a"})

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"
