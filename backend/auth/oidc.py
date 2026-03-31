from __future__ import annotations

from dataclasses import dataclass

from backend.auth.jwt_validator import JwtClaims, JwtValidator


@dataclass(frozen=True, slots=True)
class OidcValidationResult:
    claims: JwtClaims
    provider: str


class OidcAuthenticator:
    """Centralized OIDC validation abstraction for human identity."""

    def __init__(self, provider_name: str = "configured-oidc") -> None:
        self._provider_name = provider_name
        self._validator = JwtValidator()

    def validate_bearer_token(self, token: str) -> OidcValidationResult:
        claims = self._validator.parse_claims(token)
        return OidcValidationResult(claims=claims, provider=self._provider_name)
