from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType
from backend.auth.rbac import RbacAuthorizer


def test_rbac_denies_cross_tenant() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, permissions=frozenset({Permission.RUNTIME_VIEW}))
    decision = RbacAuthorizer().authorize(principal=principal, permission=Permission.RUNTIME_VIEW, tenant_id="tenant-b")
    assert decision.allowed is False


def test_rbac_allows_present_permission() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, permissions=frozenset({Permission.RUNTIME_VIEW}))
    decision = RbacAuthorizer().authorize(principal=principal, permission=Permission.RUNTIME_VIEW, tenant_id="tenant-a")
    assert decision.allowed is True
