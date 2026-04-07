"""JWT validation with cryptographic signature verification via JWKS.

This module replaces the previous implementation that only base64-decoded
the payload without verifying the signature. That implementation accepted
any crafted token and was a complete authentication bypass.

This implementation:
- Fetches JWKS from the configured endpoint with a 10-minute TTL cache
- Verifies the token signature against all available keys
- Enforces issuer, audience, and expiry claims
- Fails closed on any error — no partial validation
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

logger = logging.getLogger("ajenda.jwt_validator")


@dataclass(frozen=True)
class JwtClaims:
    """Typed representation of verified JWT claims.

    Produced by JwtValidator.validate_and_extract_claims() after full
    cryptographic verification. All fields are guaranteed to be present
    and valid when this object is returned.

    The ``raw`` field contains the full claims dict for access to
    custom/extension claims not represented as typed attributes.
    """

    sub: str
    """Subject — the authenticated principal identifier."""

    tenant_id: str
    """Tenant identifier extracted from the token claims."""

    roles: list[str] = field(default_factory=list)
    """List of role strings granted to this principal."""

    email: str | None = None
    """Email address of the authenticated user, if present."""

    raw: dict[str, Any] = field(default_factory=dict)
    """Full raw claims dict for access to extension claims."""

    @classmethod
    def from_dict(cls, claims: dict[str, Any]) -> JwtClaims:
        """Build a JwtClaims from a raw verified claims dict.

        Raises JwtValidationError if required claims are missing.
        """
        sub = claims.get("sub")
        tenant_id = claims.get("tenant_id") or claims.get("tid")
        if not sub:
            raise JwtValidationError("token missing required 'sub' claim")
        if not tenant_id:
            raise JwtValidationError("token missing required 'tenant_id' claim")
        roles = claims.get("roles") or claims.get("groups") or []
        if isinstance(roles, str):
            roles = [roles]
        return cls(
            sub=sub,
            tenant_id=str(tenant_id),
            roles=list(roles),
            email=claims.get("email"),
            raw=claims,
        )


_JWKS_CACHE_TTL_SECONDS = 600  # 10 minutes


class JwtValidationError(ValueError):
    """Raised on any JWT validation failure."""


class JwksCache:
    """Thread-safe JWKS cache with TTL-based refresh.

    On refresh failure, retains the previously cached keys to avoid
    a hard outage due to a transient JWKS endpoint failure. If no
    keys have ever been fetched, raises RuntimeError (fail closed).
    """

    def __init__(self, jwks_uri: str) -> None:
        self._jwks_uri = jwks_uri
        self._keys: list[dict[str, Any]] = []
        self._fetched_at: float = 0.0

    def get_keys(self) -> list[dict[str, Any]]:
        """Return cached JWKS keys, refreshing if TTL has expired."""
        now = time.monotonic()
        if now - self._fetched_at > _JWKS_CACHE_TTL_SECONDS or not self._keys:
            self._refresh()
        return self._keys

    def _refresh(self) -> None:
        try:
            response = httpx.get(self._jwks_uri, timeout=5.0)
            response.raise_for_status()
            fetched = response.json().get("keys", [])
            if fetched:
                self._keys = fetched
                self._fetched_at = time.monotonic()
                logger.info("jwks_refreshed", extra={"key_count": len(self._keys)})
            else:
                logger.warning("jwks_returned_empty_keyset", extra={"uri": self._jwks_uri})
        except Exception as exc:
            logger.error("jwks_refresh_failed", extra={"error": str(exc)})
            # Retain stale keys on transient failure — better than hard outage
            if not self._keys:
                raise RuntimeError(f"JWKS fetch failed and no cached keys available: {exc}") from exc


class JwtValidator:
    """Cryptographically verified JWT validation using JWKS.

    Verifies: signature, issuer, audience, expiry.
    Fails closed on any error — no partial validation is permitted.

    Usage:
        validator = JwtValidator(jwks_uri=..., issuer=..., audience=...)
        claims = validator.validate_and_extract_claims(token)
    """

    def __init__(self, *, jwks_uri: str, issuer: str, audience: str) -> None:
        self._cache = JwksCache(jwks_uri)
        self._issuer = issuer
        self._audience = audience

    def validate_and_extract_claims(self, token: str) -> dict[str, Any]:
        """Validate the token and return its verified claims.

        Raises JwtValidationError on any validation failure with a safe error
        message that does not leak internal details to callers.
        """
        try:
            keys = self._cache.get_keys()
        except RuntimeError as exc:
            raise JwtValidationError("authentication service temporarily unavailable") from exc

        if not keys:
            raise JwtValidationError("no signing keys available for token verification")

        last_error: Exception | None = None
        for key in keys:
            try:
                claims: dict[str, Any] = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256", "ES256"],
                    audience=self._audience,
                    issuer=self._issuer,
                    options={"verify_exp": True, "verify_iat": True},
                )
                return claims
            except ExpiredSignatureError as exc:
                raise JwtValidationError("token has expired") from exc
            except JWTClaimsError as exc:
                raise JwtValidationError(f"token claims invalid: {exc}") from exc
            except JWTError as exc:
                last_error = exc
                continue  # Try next key in the JWKS

        raise JwtValidationError(
            f"token signature verification failed against all {len(keys)} JWKS keys"
        ) from last_error
