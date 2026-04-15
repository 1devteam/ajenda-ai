from fastapi import FastAPI

from backend.api.routes.system import router


def test_system_status_routes_register() -> None:
    app = FastAPI()
    app.include_router(router)
    routes = {route.path for route in app.routes}
    assert "/system/health" in routes
    assert "/system/readiness" in routes
    assert "/system/status" in routes
