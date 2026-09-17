from __future__ import annotations

from dataclasses import dataclass

from backend.auth.permissions import Permission
from backend.auth.principal import Principal, PrincipalType


@dataclass(frozen=True, slots=True)
class RoleBinding:
    role_name: str
    permissions: frozenset[Permission]


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reason: str


class RbacAuthorizer:
    def __init__(self) -> None:
        self._roles: dict[str, frozenset[Permission]] = {
            "admin": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.AUTH_MANAGE,
                    Permission.API_KEYS_CREATE,
                    Permission.API_KEYS_READ,
                    Permission.API_KEYS_REVOKE,
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.MISSION_CREATE,
                    Permission.MISSION_MANAGE,
                    Permission.RUNTIME_OPERATE,
                    Permission.PLATFORM_OPERATE,
                    Permission.PROVISION_WORKFORCE,
                    Permission.RUNTIME_VIEW,
                    Permission.CAPABILITY_MANAGE,
                    Permission.EVIDENCE_MANAGE,
                    Permission.OUTCOME_REVIEW_MANAGE,
                    Permission.RETRIEVAL_MANAGE,
                    Permission.BUSINESS_PROFILE_READ,
                    Permission.BUSINESS_PROFILE_MANAGE,
                    Permission.ACCOUNT_READ,
                    Permission.CREDENTIALS_READ,
                    Permission.CREDENTIALS_MANAGE,
                    Permission.BILLING_READ,
                    Permission.BILLING_MANAGE,
                }
            ),
            "tenant_owner": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.AUTH_MANAGE,
                    Permission.API_KEYS_CREATE,
                    Permission.API_KEYS_READ,
                    Permission.API_KEYS_REVOKE,
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.MISSION_CREATE,
                    Permission.MISSION_MANAGE,
                    Permission.RUNTIME_OPERATE,
                    Permission.PROVISION_WORKFORCE,
                    Permission.RUNTIME_VIEW,
                    Permission.CAPABILITY_MANAGE,
                    Permission.EVIDENCE_MANAGE,
                    Permission.OUTCOME_REVIEW_MANAGE,
                    Permission.RETRIEVAL_MANAGE,
                    Permission.BUSINESS_PROFILE_READ,
                    Permission.BUSINESS_PROFILE_MANAGE,
                    Permission.ACCOUNT_READ,
                    Permission.CREDENTIALS_READ,
                    Permission.CREDENTIALS_MANAGE,
                    Permission.BILLING_READ,
                    Permission.BILLING_MANAGE,
                }
            ),
            "tenant_admin": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.AUTH_MANAGE,
                    Permission.API_KEYS_CREATE,
                    Permission.API_KEYS_READ,
                    Permission.API_KEYS_REVOKE,
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.MISSION_CREATE,
                    Permission.MISSION_MANAGE,
                    Permission.RUNTIME_OPERATE,
                    Permission.PROVISION_WORKFORCE,
                    Permission.RUNTIME_VIEW,
                    Permission.CAPABILITY_MANAGE,
                    Permission.EVIDENCE_MANAGE,
                    Permission.OUTCOME_REVIEW_MANAGE,
                    Permission.RETRIEVAL_MANAGE,
                    Permission.BUSINESS_PROFILE_READ,
                    Permission.BUSINESS_PROFILE_MANAGE,
                    Permission.ACCOUNT_READ,
                    Permission.CREDENTIALS_READ,
                    Permission.CREDENTIALS_MANAGE,
                    Permission.BILLING_READ,
                    Permission.BILLING_MANAGE,
                }
            ),
            "operator": frozenset(
                {
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.MISSION_MANAGE,
                    Permission.RUNTIME_OPERATE,
                    Permission.RUNTIME_VIEW,
                    Permission.BUSINESS_PROFILE_READ,
                }
            ),
            "guardian": frozenset(
                {
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.OUTCOME_REVIEW_MANAGE,
                    Permission.EVIDENCE_MANAGE,
                }
            ),
            "viewer": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.EXECUTION_VIEW,
                    Permission.RUNTIME_VIEW,
                    Permission.BUSINESS_PROFILE_READ,
                    Permission.ACCOUNT_READ,
                    Permission.CREDENTIALS_READ,
                    Permission.BILLING_READ,
                }
            ),
            "machine_executor": frozenset(
                {
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                }
            ),
            "signup_bootstrap": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.ACCOUNT_READ,
                    Permission.MISSION_CREATE,
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.RUNTIME_VIEW,
                    Permission.BUSINESS_PROFILE_READ,
                }
            ),
            "tenant_operator": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.ACCOUNT_READ,
                    Permission.BILLING_READ,
                    Permission.BILLING_MANAGE,
                    Permission.MISSION_CREATE,
                    Permission.MISSION_MANAGE,
                    Permission.RUNTIME_OPERATE,
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.RUNTIME_VIEW,
                    Permission.BUSINESS_PROFILE_READ,
                    Permission.BUSINESS_PROFILE_MANAGE,
                    Permission.API_KEYS_CREATE,
                    Permission.API_KEYS_READ,
                    Permission.API_KEYS_REVOKE,
                    Permission.CREDENTIALS_READ,
                    Permission.CREDENTIALS_MANAGE,
                }
            ),
        }

    def resolve_permissions(self, roles: tuple[str, ...]) -> frozenset[Permission]:
        permissions: set[Permission] = set()
        for role in roles:
            permissions.update(self._roles.get(role, frozenset()))
        return frozenset(permissions)

    def _effective_permissions(self, principal: Principal) -> set[Permission]:
        effective_permissions = set(principal.permissions)
        effective_permissions.update(self.resolve_permissions(tuple(principal.roles)))
        return effective_permissions

    def authorize(self, *, principal: Principal, permission: Permission, tenant_id: str) -> AuthorizationDecision:
        if principal.tenant_id != tenant_id:
            return AuthorizationDecision(False, "cross-tenant access denied")
        if permission not in self._effective_permissions(principal):
            return AuthorizationDecision(False, f"missing permission: {permission.value}")
        return AuthorizationDecision(True, "authorized")

    def authorize_platform(self, *, principal: Principal, permission: Permission) -> AuthorizationDecision:
        """Authorize a platform-scoped operation that is not owned by one tenant.

        Platform authority is intentionally narrower than ordinary tenant RBAC:
        only authenticated human principals carrying the explicit ``admin`` role
        may exercise platform permissions. Tenant roles and machine API keys are
        never promoted into global authority by sharing a tenant permission.
        """
        if principal.principal_type != PrincipalType.USER:
            return AuthorizationDecision(False, "platform operations require a human principal")
        if "admin" not in principal.roles:
            return AuthorizationDecision(False, "platform operations require the admin role")
        if permission not in self._effective_permissions(principal):
            return AuthorizationDecision(False, f"missing permission: {permission.value}")
        return AuthorizationDecision(True, "authorized")
