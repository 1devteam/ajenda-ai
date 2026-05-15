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


def test_rbac_resolves_role_permissions_at_authorization_time() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, roles=("operator",))
    decision = RbacAuthorizer().authorize(
        principal=principal, permission=Permission.RUNTIME_OPERATE, tenant_id="tenant-a"
    )
    assert decision.allowed is True


def test_rbac_viewer_cannot_operate_runtime_or_queue_work() -> None:
    principal = Principal("u1", "tenant-a", PrincipalType.USER, roles=("viewer",))
    authorizer = RbacAuthorizer()

    runtime_decision = authorizer.authorize(
        principal=principal, permission=Permission.RUNTIME_OPERATE, tenant_id="tenant-a"
    )
    queue_decision = authorizer.authorize(
        principal=principal, permission=Permission.EXECUTION_QUEUE, tenant_id="tenant-a"
    )

    assert runtime_decision.allowed is False
    assert queue_decision.allowed is False
