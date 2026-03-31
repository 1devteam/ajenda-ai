from __future__ import annotations

from dataclasses import dataclass

from backend.auth.permissions import Permission
from backend.auth.principal import Principal


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
            "tenant_admin": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.AUTH_MANAGE,
                    Permission.API_KEYS_CREATE,
                    Permission.API_KEYS_READ,
                    Permission.API_KEYS_REVOKE,
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.PROVISION_WORKFORCE,
                    Permission.RUNTIME_VIEW,
                }
            ),
            "operator": frozenset(
                {
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                    Permission.RUNTIME_VIEW,
                }
            ),
            "viewer": frozenset(
                {
                    Permission.AUTH_READ,
                    Permission.EXECUTION_VIEW,
                    Permission.RUNTIME_VIEW,
                }
            ),
            "machine_executor": frozenset(
                {
                    Permission.EXECUTION_VIEW,
                    Permission.EXECUTION_QUEUE,
                }
            ),
        }

    def resolve_permissions(self, roles: tuple[str, ...]) -> frozenset[Permission]:
        permissions: set[Permission] = set()
        for role in roles:
            permissions.update(self._roles.get(role, frozenset()))
        return frozenset(permissions)

    def authorize(self, *, principal: Principal, permission: Permission, tenant_id: str) -> AuthorizationDecision:
        if principal.tenant_id != tenant_id:
            return AuthorizationDecision(False, "cross-tenant access denied")
        if permission not in principal.permissions:
            return AuthorizationDecision(False, f"missing permission: {permission.value}")
        return AuthorizationDecision(True, "authorized")
