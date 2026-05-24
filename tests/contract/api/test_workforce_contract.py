from backend.api.routes import workforce


def test_workforce_route_prefix():
    assert workforce.router.prefix == "/workforces"


def test_workforce_has_provision_endpoint():
    paths = [route.path for route in workforce.router.routes]
    assert any("provision" in p for p in paths)
