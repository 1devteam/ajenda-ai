"""OIDC authentication adapter.

Wraps JwtValidator with application-level settings injection.
The OidcAuthenticator is the single entry point for all Bearer token validation.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.auth.jwt_validator import JwtClaims, JwtValidationError, JwtValidator
from backend.auth.principal import PrincipalType, UserPrincipal


@dataclass(frozen=True, slots=True)
class OidcValidationResult:
    claims: JwtClaims
    principal: UserPrincipal
    provider: str


class OidcAuthenticator:
    """Centralized OIDC validation abstraction for human identity.

    Requires JWKS URI, issuer, and audience from application settings.
    These must be explicitly configured — there are no defaults.
    """

    def __init__(
        self,
        *,
        jwks_uri: str,
        issuer: str,
        audience: str,
        provider_name: str = "oidc",
    ) -> None:
        self._provider_name = provider_name
        self._validator = JwtValidator(
            jwks_uri=jwks_uri,
            issuer=issuer,
            audience=audience,
        )

    def validate_bearer_token(self, token: str) -> OidcValidationResult:
        """Validate a Bearer token and return a verified OidcValidationResult.

        Raises JwtValidationError on any failure. Never returns partial results.
        """
        claims = self._validator.validate_and_extract_claims(token)

        if not claims.sub.strip():
            raise JwtValidationError("token missing required 'sub' claim")
        if not claims.tenant_id.strip():
            raise JwtValidationError("token missing required 'tenant_id' claim")

        principal = UserPrincipal(
            subject_id=claims.sub,
            tenant_id=claims.tenant_id,
            principal_type=PrincipalType.USER,
            roles=tuple(claims.roles),
            email=claims.email,
        )
        return OidcValidationResult(
            claims=claims,
            principal=principal,
            provider=self._provider_name,
        )
