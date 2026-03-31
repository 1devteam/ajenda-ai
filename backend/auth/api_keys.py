from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    key_id: str
    tenant_id: str
    hashed_secret: str
    scopes: tuple[str, ...]
    revoked: bool
    created_at: datetime


class ApiKeyHasher:
    def generate_plaintext(self) -> str:
        return secrets.token_urlsafe(32)

    def hash_secret(self, secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    def verify(self, *, plaintext: str, hashed_secret: str) -> bool:
        return hmac.compare_digest(self.hash_secret(plaintext), hashed_secret)

    def build_record(self, *, tenant_id: str, scopes: tuple[str, ...]) -> tuple[str, ApiKeyRecord]:
        plaintext = self.generate_plaintext()
        key_id = secrets.token_hex(8)
        record = ApiKeyRecord(
            key_id=key_id,
            tenant_id=tenant_id,
            hashed_secret=self.hash_secret(plaintext),
            scopes=scopes,
            revoked=False,
            created_at=datetime.now(timezone.utc),
        )
        return plaintext, record
