from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import create_app


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
