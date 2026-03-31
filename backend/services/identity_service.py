from __future__ import annotations

from backend.auth.oidc import OidcAuthenticator
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.auth.rbac import RbacAuthorizer


class IdentityService:
    def __init__(self) -> None:
        self._oidc = OidcAuthenticator()
        self._rbac = RbacAuthorizer()

    def authenticate_user_bearer(self, token: str) -> UserPrincipal:
        result = self._oidc.validate_bearer_token(token)
        permissions = self._rbac.resolve_permissions(result.claims.roles)
        return UserPrincipal(
            subject_id=result.claims.subject,
            tenant_id=result.claims.tenant_id,
            principal_type=PrincipalType.USER,
            roles=result.claims.roles,
            permissions=permissions,
            email=result.claims.email,
        )
