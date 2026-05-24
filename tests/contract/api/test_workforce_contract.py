from backend.api.routes import workforce


def test_workforce_route_prefix():
    assert workforce.router.prefix == "/workforces"


def test_workforce_has_post_provision_endpoint():
    assert any(route.path == "/workforces/provision" and "POST" in route.methods for route in workforce.router.routes)
