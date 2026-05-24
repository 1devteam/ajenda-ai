from backend.api.routes import admin


def test_admin_route_prefix():
    assert admin.router.prefix == "/admin"


def test_admin_requires_role_check():
    assert hasattr(admin, "_require_admin")
