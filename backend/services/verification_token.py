"""Verification token issuance and validation for onboarding."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_PASSWORD_HASHER = PasswordHasher()


@dataclass(frozen=True, slots=True)
class IssuedVerificationToken:
    plaintext: str
    token_hash: str
    expires_at: datetime


class VerificationTokenIssuer:
    """Issue and verify signup email verification tokens."""

    def __init__(self, *, ttl_hours: int = 24) -> None:
        self._ttl_hours = ttl_hours

    def issue(self, *, now: datetime | None = None) -> IssuedVerificationToken:
        """Generate a new verification token and Argon2id hash."""
        current = now or datetime.now(UTC)
        plaintext = secrets.token_urlsafe(32)
        token_hash = str(_PASSWORD_HASHER.hash(plaintext))
        expires_at = current + timedelta(hours=self._ttl_hours)
        return IssuedVerificationToken(
            plaintext=plaintext,
            token_hash=token_hash,
            expires_at=expires_at,
        )

    def verify(self, *, plaintext: str, token_hash: str) -> bool:
        """Constant-time verification of a plaintext token against a stored hash."""
        try:
            return bool(_PASSWORD_HASHER.verify(token_hash, plaintext))
        except VerifyMismatchError:
            return False
