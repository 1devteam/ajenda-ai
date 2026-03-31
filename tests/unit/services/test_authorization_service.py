import pytest

from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType
from backend.services.authorization_service import AuthorizationService


def test_authorization_service_denies_missing_permission() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, permissions=frozenset())
    with pytest.raises(PermissionError):
        AuthorizationService().require(principal=principal, permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")
