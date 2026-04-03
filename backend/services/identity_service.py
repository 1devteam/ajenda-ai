from __future__ import annotations
from backend.auth.oidc import OidcAuthenticator
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.auth.rbac import RbacAuthorizer


class IdentityService:
    """Service that authenticates users via OIDC Bearer tokens.
    
    Delegates JWT validation to OidcAuthenticator and RBAC resolution
    to RbacAuthorizer. The OidcAuthenticator requires JWKS configuration
    injected at construction time via the application settings.
    """

    def __init__(self, oidc: OidcAuthenticator | None = None) -> None:
        # OidcAuthenticator is injected to allow testing without a live JWKS endpoint.
        # In production, it is constructed by the dependency injection layer with
        # settings-backed jwks_uri, issuer, and audience.
        self._oidc = oidc
        self._rbac = RbacAuthorizer()

    def authenticate_user_bearer(self, token: str) -> UserPrincipal:
        """Validate a Bearer token and return a verified UserPrincipal.
        
        Raises JwtValidationError on any validation failure.
        """
        if self._oidc is None:
            raise RuntimeError(
                "IdentityService requires an OidcAuthenticator. "
                "Inject one via the constructor or use the DI layer."
            )
        result = self._oidc.validate_bearer_token(token)
        # result.principal is already built by OidcAuthenticator with verified claims.
        # We add RBAC permissions on top.
        roles = result.principal.roles
        permissions = self._rbac.resolve_permissions(list(roles))
        return UserPrincipal(
            subject_id=result.principal.subject_id,
            tenant_id=result.principal.tenant_id,
            principal_type=PrincipalType.USER,
            roles=roles,
            permissions=permissions,
            email=result.principal.email,
        )
