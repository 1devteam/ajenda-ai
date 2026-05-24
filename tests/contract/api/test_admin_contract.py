import inspect
from backend.api.router import build_api_router
from backend.api.routes import admin


def test_admin_route_prefix():
    assert admin.router.prefix == "/admin"


def test_admin_routes_exist_and_call_require_admin():
    api_router = build_api_router()
    admin_routes = [r for r in api_router.routes if r.path.startswith("/v1/admin")]
    assert len(admin_routes) > 0

    for route in admin_routes:
        if hasattr(route, "endpoint"):
            src = inspect.getsource(route.endpoint)
            assert "_require_admin" in src
