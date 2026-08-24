from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType
from backend.auth.rbac import RbacAuthorizer


def test_admin_human_can_operate_platform() -> None:
    principal = Principal(
        subject_id="admin-user",
        tenant_id="admin-home-tenant",
        principal_type=PrincipalType.USER,
        roles=("admin",),
    )

    decision = RbacAuthorizer().authorize_platform(
        principal=principal,
        permission=Permission.PLATFORM_OPERATE,
    )

    assert decision.allowed is True


def test_tenant_owner_cannot_operate_platform() -> None:
    principal = Principal(
        subject_id="owner-user",
        tenant_id="tenant-a",
        principal_type=PrincipalType.USER,
        roles=("tenant_owner",),
    )

    decision = RbacAuthorizer().authorize_platform(
        principal=principal,
        permission=Permission.PLATFORM_OPERATE,
    )

    assert decision.allowed is False


def test_tenant_admin_cannot_operate_platform() -> None:
    principal = Principal(
        subject_id="tenant-admin-user",
        tenant_id="tenant-a",
        principal_type=PrincipalType.USER,
        roles=("tenant_admin",),
    )

    decision = RbacAuthorizer().authorize_platform(
        principal=principal,
        permission=Permission.PLATFORM_OPERATE,
    )

    assert decision.allowed is False


def test_operator_runtime_permission_does_not_grant_platform_authority() -> None:
    principal = Principal(
        subject_id="operator-user",
        tenant_id="tenant-a",
        principal_type=PrincipalType.USER,
        roles=("operator",),
    )
    authorizer = RbacAuthorizer()

    tenant_decision = authorizer.authorize(
        principal=principal,
        permission=Permission.RUNTIME_OPERATE,
        tenant_id="tenant-a",
    )
    platform_decision = authorizer.authorize_platform(
        principal=principal,
        permission=Permission.PLATFORM_OPERATE,
    )

    assert tenant_decision.allowed is True
    assert platform_decision.allowed is False


def test_machine_cannot_gain_platform_authority_from_admin_role() -> None:
    principal = Principal(
        subject_id="machine:k1",
        tenant_id="tenant-a",
        principal_type=PrincipalType.MACHINE,
        roles=("admin",),
    )

    decision = RbacAuthorizer().authorize_platform(
        principal=principal,
        permission=Permission.PLATFORM_OPERATE,
    )

    assert decision.allowed is False
