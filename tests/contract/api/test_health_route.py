from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


class _ExplodingDependency:
    def ping(self) -> bool:
        raise RuntimeError("redis://username:password@internal-host:6379/0")


def test_health_route_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_component_statuses() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/readiness")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": {"status": "ready"}, "queue": {"status": "ready"}},
        "reason": None,
    }


def test_health_does_not_touch_dependency_pings() -> None:
    app = create_app()
    app.state.database_runtime = _ExplodingDependency()
    app.state.queue_adapter = _ExplodingDependency()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_when_database_runtime_missing() -> None:
    app = create_app()
    delattr(app.state, "database_runtime")
    with TestClient(app) as client:
        response = client.get("/readiness")
    assert response.status_code == 503
    assert response.json()["dependencies"]["database"] == {
        "status": "unavailable",
        "reason": "DATABASE_UNAVAILABLE",
    }


def test_readiness_returns_503_when_queue_adapter_missing() -> None:
    app = create_app()
    delattr(app.state, "queue_adapter")
    with TestClient(app) as client:
        response = client.get("/readiness")
    assert response.status_code == 503
    assert response.json()["dependencies"]["queue"] == {"status": "unavailable", "reason": "QUEUE_UNAVAILABLE"}


def test_readiness_returns_503_when_database_ping_raises() -> None:
    app = create_app()
    app.state.database_runtime = _ExplodingDependency()
    with TestClient(app) as client:
        response = client.get("/readiness")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "DEPENDENCY_UNAVAILABLE"
    assert payload["dependencies"]["database"] == {"status": "unavailable", "reason": "DATABASE_UNAVAILABLE"}
    assert "redis://" not in str(payload)


def test_readiness_returns_503_when_queue_ping_raises() -> None:
    app = create_app()
    app.state.queue_adapter = _ExplodingDependency()
    with TestClient(app) as client:
        response = client.get("/readiness")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "DEPENDENCY_UNAVAILABLE"
    assert payload["dependencies"]["queue"] == {"status": "unavailable", "reason": "QUEUE_UNAVAILABLE"}
    assert "internal-host" not in str(payload)
