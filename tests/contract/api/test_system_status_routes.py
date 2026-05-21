from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


def test_system_status_routes_register() -> None:
    app = create_app()
    routes = {route.path for route in app.routes}
    assert "/v1/system/health" in routes
    assert "/v1/system/readiness" in routes
    assert "/v1/system/status" in routes


def test_system_health_is_public_liveness() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_readiness_is_public_dependency_readiness() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/system/readiness")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_system_status_remains_protected() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/system/status")
    assert response.status_code == 400
