from __future__ import annotations

import pytest
from argon2.exceptions import InvalidHashError

from backend.auth.api_keys import ApiKeyHasher


def test_api_key_hasher_verifies_plaintext() -> None:
    hasher = ApiKeyHasher()
    plaintext = hasher.generate_plaintext()
    hashed = hasher.hash_secret(plaintext)
    assert hasher.verify(plaintext=plaintext, hashed_secret=hashed) is True


def test_api_key_hasher_rejects_wrong_secret() -> None:
    hasher = ApiKeyHasher()
    hashed = hasher.hash_secret("correct")
    assert hasher.verify(plaintext="wrong", hashed_secret=hashed) is False


def test_api_key_hasher_raises_for_invalid_hash() -> None:
    hasher = ApiKeyHasher()
    with pytest.raises(InvalidHashError):
        hasher.verify(plaintext="secret", hashed_secret="not-an-argon2-hash")


def test_api_key_hasher_builds_record_without_storing_plaintext() -> None:
    hasher = ApiKeyHasher()
    plaintext, record = hasher.build_record(tenant_id="tenant-1", scopes=("tasks:read",))

    assert plaintext != record.hashed_secret
    assert record.tenant_id == "tenant-1"
    assert record.scopes == ("tasks:read",)
    assert record.revoked is False
    assert hasher.verify(plaintext=plaintext, hashed_secret=record.hashed_secret) is True


def test_api_key_repository_revoke_sets_updated_at_and_revoked_at() -> None:
    from unittest.mock import MagicMock

    from backend.domain.api_key_record import ApiKeyRecordModel
    from backend.repositories.api_key_repository import ApiKeyRepository

    session = MagicMock()
    record = ApiKeyRecordModel(tenant_id="tenant-1", key_id="key-1", hashed_secret="$argon2id$hash")

    ApiKeyRepository(session).revoke(record)

    assert record.revoked is True
    assert record.revoked_at is not None
    assert record.updated_at == record.revoked_at
    session.flush.assert_called_once()
