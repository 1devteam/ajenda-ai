from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any


class JwtValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class JwtClaims:
    subject: str
    tenant_id: str
    roles: tuple[str, ...]
    email: str | None
    issuer: str | None
    audience: str | None


class JwtValidator:
    """Strict JWT parser for Phase 3 contract tests.

    Signature verification is delegated to the OIDC adapter layer. This validator
    parses claims and enforces presence of required identity fields.
    """

    def parse_claims(self, token: str) -> JwtClaims:
        parts = token.split(".")
        if len(parts) < 2:
            raise JwtValidationError("invalid jwt structure")
        payload = self._decode_segment(parts[1])
        subject = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        roles = tuple(payload.get("roles", []))
        if not isinstance(subject, str) or not subject.strip():
            raise JwtValidationError("missing subject")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise JwtValidationError("missing tenant_id")
        if not isinstance(roles, tuple):
            roles = tuple(roles)
        return JwtClaims(
            subject=subject,
            tenant_id=tenant_id,
            roles=roles,
            email=payload.get("email"),
            issuer=payload.get("iss"),
            audience=payload.get("aud"),
        )

    @staticmethod
    def _decode_segment(segment: str) -> dict[str, Any]:
        padding = "=" * (-len(segment) % 4)
        try:
            decoded = base64.urlsafe_b64decode((segment + padding).encode("utf-8"))
            payload = json.loads(decoded.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise JwtValidationError("invalid jwt payload") from exc
        if not isinstance(payload, dict):
            raise JwtValidationError("jwt payload must be an object")
        return payload
