from fastapi.testclient import TestClient

from backend.main import create_app


class _FailIfCalled:
    def ping(self) -> bool:
        raise AssertionError("dependency ping should not be called for health")


def test_health_route_returns_ok() -> None:
    app = create_app()
    app.state.database_runtime = _FailIfCalled()
    app.state.queue_adapter = _FailIfCalled()
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
