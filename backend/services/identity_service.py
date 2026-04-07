"""Identity service — authenticates principals from Bearer tokens and API keys.

Wraps OidcAuthenticator and RbacAuthorizer to produce typed Principal objects.
Accepts dependency-injected authenticator for testability.
"""

from __future__ import annotations

from backend.auth.oidc import OidcAuthenticator
from backend.auth.principal import UserPrincipal
from backend.auth.rbac import RbacAuthorizer


class IdentityService:
    """Authenticates principals from Bearer tokens.

    Args:
        oidc_authenticator: Optional injected OidcAuthenticator. If not
            provided, a default instance is created. Inject for testing.
        session: Optional DB session (reserved for future API key auth path).
    """

    def __init__(
        self,
        oidc_authenticator: OidcAuthenticator | None = None,
        session: object | None = None,
    ) -> None:
        self._oidc = oidc_authenticator if oidc_authenticator is not None else OidcAuthenticator()
        self._rbac = RbacAuthorizer()
        self._session = session  # reserved for future API key auth integration

    def authenticate_bearer(self, token: str) -> UserPrincipal:
        """Authenticate a Bearer token and return a typed UserPrincipal.

        Raises JwtValidationError on any validation failure.
        """
        if not token:
            raise ValueError("token must not be empty")
        return self._oidc.authenticate(token)

    def authenticate_user_bearer(self, token: str) -> UserPrincipal:
        """Alias for authenticate_bearer for backward compatibility."""
        return self.authenticate_bearer(token)
