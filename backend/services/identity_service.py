from __future__ import annotations

from backend.auth.oidc import OidcAuthenticator
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.auth.rbac import RbacAuthorizer


class IdentityService:
    """Authenticates users through an injected OIDC authenticator."""

    def __init__(self, oidc: OidcAuthenticator | None = None) -> None:
        self._oidc = oidc
        self._rbac = RbacAuthorizer()

    def authenticate_user_bearer(self, token: str) -> UserPrincipal:
        if self._oidc is None:
            raise RuntimeError(
                "IdentityService requires an OidcAuthenticator. "
                "Inject one through the application dependency layer."
            )

        result = self._oidc.validate_bearer_token(token)
        roles = tuple(result.principal.roles)
        permissions = self._rbac.resolve_permissions(list(roles))

        return UserPrincipal(
            subject_id=result.principal.subject_id,
            tenant_id=result.principal.tenant_id,
            principal_type=PrincipalType.USER,
            roles=roles,
            permissions=permissions,
            email=result.principal.email,
        )
