from backend.api.routes import branch


def test_branch_route_prefix():
    assert branch.router.prefix == "/branches"


def test_branch_has_create_endpoint():
    paths = [route.path for route in branch.router.routes]
    assert "" in [p.replace("/branches", "") for p in paths]
