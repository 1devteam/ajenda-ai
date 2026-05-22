from fastapi.testclient import TestClient

from backend.main import create_app


def test_system_status_routes_register() -> None:
    app = create_app()
    routes = {route.path for route in app.router.routes}
    assert "/v1/system/health" in routes
    assert "/v1/system/readiness" in routes
    assert "/v1/system/status" in routes


def test_versioned_health_and_readiness_are_public_and_status_is_protected() -> None:
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/v1/system/health").status_code == 200
        assert client.get("/v1/system/readiness").status_code in {200, 503}
        assert client.get("/v1/system/status").status_code in {400, 401, 403}
