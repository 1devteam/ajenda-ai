"""ID token validation for browser OIDC login (no tenant_id claim required)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError

from backend.auth.jwt_validator import JwksCache, JwtValidationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IdTokenClaims:
    sub: str
    email: str
    email_verified: bool
    nonce: str | None = None


class IdTokenValidator:
    """Validate OIDC id_tokens for login exchange."""

    def __init__(self, *, jwks_uri: str, issuer: str, audience: str) -> None:
        self._cache = JwksCache(jwks_uri)
        self._issuer = issuer.rstrip("/")
        self._audience = audience

    def validate(
        self,
        token: str,
        *,
        expected_nonce: str | None = None,
        access_token: str | None = None,
    ) -> IdTokenClaims:
        try:
            keys = self._cache.get_keys()
        except RuntimeError as exc:
            raise JwtValidationError("authentication service temporarily unavailable") from exc

        if not keys:
            raise JwtValidationError("no signing keys available for token verification")

        decode_options: dict[str, bool] = {"verify_exp": True, "verify_iat": True}
        if not access_token:
            # Google (and other IdPs) may include at_hash when access_token is returned
            # alongside id_token; skip at_hash binding when access_token is unavailable.
            decode_options["verify_at_hash"] = False

        last_error: Exception | None = None
        raw_claims: dict[str, object] | None = None
        for key in keys:
            try:
                raw_claims = jwt.decode(
                    token,
                    key,
                    algorithms=["RS256", "ES256"],
                    audience=self._audience,
                    issuer=self._issuer,
                    access_token=access_token,
                    options=decode_options,
                )
                break
            except ExpiredSignatureError as exc:
                raise JwtValidationError("token has expired") from exc
            except JWTClaimsError as exc:
                raise JwtValidationError(f"token claims invalid: {exc}") from exc
            except JWTError as exc:
                last_error = exc
                continue

        if raw_claims is None:
            raise JwtValidationError("token signature verification failed") from last_error

        sub = raw_claims.get("sub")
        email = raw_claims.get("email")
        email_verified = raw_claims.get("email_verified")
        nonce = raw_claims.get("nonce")

        if not isinstance(sub, str) or not sub.strip():
            raise JwtValidationError("token missing required 'sub' claim")
        if not isinstance(email, str) or not email.strip():
            raise JwtValidationError("token missing required 'email' claim")
        if email_verified not in (True, "true", 1):
            raise JwtValidationError("email address is not verified by identity provider")

        if expected_nonce is not None:
            if not isinstance(nonce, str) or nonce != expected_nonce:
                raise JwtValidationError("token nonce mismatch")

        return IdTokenClaims(
            sub=sub.strip(),
            email=email.strip(),
            email_verified=True,
            nonce=str(nonce) if isinstance(nonce, str) else None,
        )
