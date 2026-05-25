import inspect

from backend.api.routes import admin


def test_admin_route_prefix():
    assert admin.router.prefix == "/admin"


def test_admin_routes_call_require_admin():
    for route in admin.router.routes:
        if hasattr(route, "endpoint"):
            src = inspect.getsource(route.endpoint)
            assert "_require_admin" in src
