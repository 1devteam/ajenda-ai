"""Verification code issuance and validation for onboarding."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_PASSWORD_HASHER = PasswordHasher()
_VERIFICATION_CODE_SPACE = 1_000_000


@dataclass(frozen=True, slots=True)
class IssuedVerificationToken:
    """A short-lived verification code and its one-way stored representation."""

    plaintext: str
    token_hash: str
    expires_at: datetime


class VerificationTokenIssuer:
    """Issue and verify six-digit signup email verification codes."""

    def __init__(self, *, ttl_hours: int = 24) -> None:
        self._ttl_hours = ttl_hours

    def issue(self, *, now: datetime | None = None) -> IssuedVerificationToken:
        """Generate a zero-padded six-digit code and Argon2id hash."""
        current = now or datetime.now(UTC)
        plaintext = f"{secrets.randbelow(_VERIFICATION_CODE_SPACE):06d}"
        token_hash = str(_PASSWORD_HASHER.hash(plaintext))
        expires_at = current + timedelta(hours=self._ttl_hours)
        return IssuedVerificationToken(
            plaintext=plaintext,
            token_hash=token_hash,
            expires_at=expires_at,
        )

    def verify(self, *, plaintext: str, token_hash: str) -> bool:
        """Verify one submitted code against one pending membership hash."""
        try:
            return bool(_PASSWORD_HASHER.verify(token_hash, plaintext))
        except VerifyMismatchError:
            return False
