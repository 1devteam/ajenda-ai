from backend.api.routes import branch


def test_branch_route_prefix():
    assert branch.router.prefix == "/branches"


def test_branch_has_post_create_endpoint():
    assert any(route.path == "/branches" and "POST" in route.methods for route in branch.router.routes)
