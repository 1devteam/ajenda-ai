from backend.auth.permissions import Permission


def test_auth_contract_permission_names_are_canonical() -> None:
    assert Permission.AUTH_READ.value == "auth:read"
