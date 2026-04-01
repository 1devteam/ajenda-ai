"""API key hashing and generation utilities.

Uses Argon2id via passlib for all secret storage.
SHA-256 is explicitly NOT used — it is a fast hash and unsuitable for secret storage.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timezone

from passlib.context import CryptContext

# Argon2id is memory-hard and GPU-resistant. It is the correct algorithm for
# hashing secrets that must be stored and later verified.
_PWD_CONTEXT = CryptContext(schemes=["argon2"], deprecated="auto")

_KEY_ALPHABET = string.ascii_letters + string.digits
_KEY_ID_LENGTH = 20
_KEY_SECRET_LENGTH = 40


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    key_id: str
    tenant_id: str
    hashed_secret: str
    scopes: tuple[str, ...]
    revoked: bool
    created_at: datetime


class ApiKeyHasher:
    """Argon2id-backed API key hasher and verifier."""

    def generate_plaintext(self) -> str:
        """Generate a cryptographically secure random plaintext secret."""
        return "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_SECRET_LENGTH))

    def hash_secret(self, secret: str) -> str:
        """Hash a plaintext secret using Argon2id. Returns the full hash string."""
        return _PWD_CONTEXT.hash(secret)

    def verify(self, *, plaintext: str, hashed_secret: str) -> bool:
        """Constant-time verification of a plaintext secret against a stored Argon2 hash."""
        return _PWD_CONTEXT.verify(plaintext, hashed_secret)

    def build_record(self, *, tenant_id: str, scopes: tuple[str, ...]) -> tuple[str, ApiKeyRecord]:
        """Generate a new key pair. Returns (plaintext_secret, ApiKeyRecord).

        The plaintext_secret is returned exactly once and must never be stored.
        The caller is responsible for presenting it to the user immediately.
        """
        plaintext = self.generate_plaintext()
        key_id = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(_KEY_ID_LENGTH))
        record = ApiKeyRecord(
            key_id=key_id,
            tenant_id=tenant_id,
            hashed_secret=self.hash_secret(plaintext),
            scopes=scopes,
            revoked=False,
            created_at=datetime.now(timezone.utc),
        )
        return plaintext, record
