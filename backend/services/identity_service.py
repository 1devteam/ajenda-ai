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
        oidc_authenticator: Injected OidcAuthenticator. Must be provided;
            OidcAuthenticator requires jwks_uri, issuer, and audience which
            are runtime configuration values — no safe default exists.
            Pass a configured instance from the dependency container.
        session: Optional DB session (reserved for future API key auth path).
    """

    def __init__(
        self,
        oidc_authenticator: OidcAuthenticator | None = None,
        session: object | None = None,
    ) -> None:
        # OidcAuthenticator requires jwks_uri/issuer/audience — a real instance
        # must be injected. The None default is retained for backward compatibility
        # with call sites that inject their own instance; callers that pass None
        # will receive a RuntimeError at authentication time (fail-fast).
        self._oidc: OidcAuthenticator | None = oidc_authenticator
        self._rbac = RbacAuthorizer()
        self._session = session  # reserved for future API key auth integration

    def authenticate_bearer(self, token: str) -> UserPrincipal:
        """Authenticate a Bearer token and return a typed UserPrincipal.

        Raises JwtValidationError on any validation failure.
        Raises RuntimeError if no OidcAuthenticator was injected.
        """
        if not token:
            raise ValueError("token must not be empty")
        if self._oidc is None:
            raise RuntimeError(
                "IdentityService requires an OidcAuthenticator instance. Inject one via the constructor."
            )
        validation = self._oidc.validate_bearer_token(token)
        return validation.principal

    def authenticate_user_bearer(self, token: str) -> UserPrincipal:
        """Alias for authenticate_bearer for backward compatibility."""
        return self.authenticate_bearer(token)
