from backend.api.router import build_api_router
from backend.api.routes import branch


def test_branch_route_prefix():
    assert branch.router.prefix == "/branches"


def test_branch_has_mounted_post_create_endpoint():
    api_router = build_api_router()
    assert any(route.path == "/v1/branches" and "POST" in route.methods for route in api_router.routes)
