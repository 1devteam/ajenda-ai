from fastapi.testclient import TestClient

from backend.main import create_app


def test_health_route_returns_ok() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_route_does_not_touch_runtime_dependencies() -> None:
    class _ExplodingDependency:
        def ping(self) -> bool:
            raise AssertionError("health route must not call dependency ping()")

    app = create_app()
    app.state.database_runtime = _ExplodingDependency()
    app.state.queue_adapter = _ExplodingDependency()

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
