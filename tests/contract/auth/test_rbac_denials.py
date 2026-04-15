import pytest

from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType
from backend.services.authorization_service import AuthorizationService


def test_cross_tenant_authorization_denied() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, permissions=frozenset({Permission.RUNTIME_VIEW}))
    with pytest.raises(PermissionError):
        AuthorizationService().require(principal=principal, permission=Permission.RUNTIME_VIEW, tenant_id="tenant-b")
