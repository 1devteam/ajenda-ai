"""Ajenda-issued customer session access tokens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from backend.auth.jwt_validator import JwtValidationError


@dataclass(frozen=True, slots=True)
class SessionAccessClaims:
    jti: str
    member_id: str
    tenant_id: str
    email: str
    roles: tuple[str, ...]
    expires_at: datetime


class SessionTokenService:
    """Issue and validate short-lived Ajenda access tokens for human principals."""

    def __init__(
        self,
        *,
        signing_secret: str,
        issuer: str = "ajenda",
        access_ttl_seconds: int = 3600,
    ) -> None:
        if len(signing_secret.strip()) < 32:
            raise ValueError("session signing secret must be at least 32 characters")
        self._secret = signing_secret
        self._issuer = issuer
        self._access_ttl_seconds = access_ttl_seconds

    def issue_access_token(
        self,
        *,
        member_id: uuid.UUID,
        tenant_id: uuid.UUID,
        email: str,
        roles: tuple[str, ...],
        jti: str | None = None,
    ) -> tuple[str, datetime]:
        now = datetime.now(tz=UTC)
        expires_at = now + timedelta(seconds=self._access_ttl_seconds)
        token_jti = jti or uuid.uuid4().hex
        payload: dict[str, Any] = {
            "iss": self._issuer,
            "sub": str(member_id),
            "tenant_id": str(tenant_id),
            "email": email,
            "roles": list(roles),
            "typ": "customer_access",
            "jti": token_jti,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        token = jwt.encode(payload, self._secret, algorithm="HS256")
        return str(token), expires_at

    def validate_access_token(self, token: str) -> SessionAccessClaims:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                options={"verify_aud": False, "verify_exp": True, "verify_iat": True},
            )
        except ExpiredSignatureError as exc:
            raise JwtValidationError("session has expired") from exc
        except JWTError as exc:
            raise JwtValidationError("invalid session token") from exc

        if claims.get("typ") != "customer_access":
            raise JwtValidationError("invalid session token type")

        jti = claims.get("jti")
        sub = claims.get("sub")
        tenant_id = claims.get("tenant_id")
        email = claims.get("email")
        roles = claims.get("roles") or []
        exp = claims.get("exp")

        if not all(isinstance(value, str) and value.strip() for value in (jti, sub, tenant_id, email)):
            raise JwtValidationError("session token missing required claims")
        if not isinstance(roles, list):
            raise JwtValidationError("session token roles claim invalid")
        if not isinstance(exp, int):
            raise JwtValidationError("session token missing expiry")

        normalized_roles = tuple(str(role) for role in roles)
        return SessionAccessClaims(
            jti=str(jti),
            member_id=str(sub),
            tenant_id=str(tenant_id),
            email=str(email),
            roles=normalized_roles,
            expires_at=datetime.fromtimestamp(exp, tz=UTC),
        )
