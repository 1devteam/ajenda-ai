from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


class _ExplodingDependency:
    def ping(self) -> bool:
        raise RuntimeError("postgresql://user:pass@db.internal:5432/ajenda")


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


def test_system_health_does_not_touch_dependencies() -> None:
    app = create_app()
    app.state.database_runtime = _ExplodingDependency()
    app.state.queue_adapter = _ExplodingDependency()
    with TestClient(app) as client:
        response = client.get("/v1/system/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_readiness_returns_503_when_database_runtime_missing() -> None:
    app = create_app()
    delattr(app.state, "database_runtime")
    with TestClient(app) as client:
        response = client.get("/v1/system/readiness")
    assert response.status_code == 503


def test_system_readiness_returns_503_when_queue_adapter_missing() -> None:
    app = create_app()
    delattr(app.state, "queue_adapter")
    with TestClient(app) as client:
        response = client.get("/v1/system/readiness")
    assert response.status_code == 503


def test_system_readiness_returns_503_when_database_ping_raises() -> None:
    app = create_app()
    app.state.database_runtime = _ExplodingDependency()
    with TestClient(app) as client:
        response = client.get("/v1/system/readiness")
    payload = response.json()
    assert response.status_code == 503
    assert payload["dependencies"]["database"] == {"status": "unavailable", "reason": "DATABASE_UNAVAILABLE"}
    assert "postgresql://" not in str(payload)


def test_system_readiness_returns_503_when_queue_ping_raises() -> None:
    app = create_app()
    app.state.queue_adapter = _ExplodingDependency()
    with TestClient(app) as client:
        response = client.get("/v1/system/readiness")
    payload = response.json()
    assert response.status_code == 503
    assert payload["dependencies"]["queue"] == {"status": "unavailable", "reason": "QUEUE_UNAVAILABLE"}
    assert "db.internal" not in str(payload)
