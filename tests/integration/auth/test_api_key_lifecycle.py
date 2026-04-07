"""Integration test: API key lifecycle against a real PostgreSQL database.

Replaces the SQLite-backed version which masked:
- Argon2id hash storage (SQLite does not enforce column types)
- UUID primary key handling (psycopg vs sqlite differ)
- JSONB column behavior
- The api_key_records table schema from migration 0002

This test uses the pg_session fixture from tests/integration/conftest.py
which provides a real PostgreSQL connection that is rolled back after the test.
"""

from __future__ import annotations

import pytest

from backend.services.api_key_service import ApiKeyService

pytestmark = pytest.mark.integration


class TestApiKeyLifecycle:
    def test_create_and_authenticate(self, pg_session) -> None:
        """Creating a key and authenticating with it must succeed."""
        service = ApiKeyService(pg_session)
        plaintext, record = service.create_key(
            tenant_id="tenant-integration-a",
            scopes=("execution:queue",),
        )
        assert plaintext and len(plaintext) > 20
        pg_session.flush()
        assert record.key_id is not None
        assert record.tenant_id == "tenant-integration-a"
        assert record.revoked is False

        principal = service.authenticate_machine(
            tenant_id="tenant-integration-a",
            key_id=record.key_id,
            plaintext=plaintext,
        )
        assert principal is not None
        assert principal.key_id == record.key_id
        assert principal.tenant_id == "tenant-integration-a"

    def test_wrong_plaintext_returns_none(self, pg_session) -> None:
        """Authentication with wrong plaintext must return None, not raise."""
        service = ApiKeyService(pg_session)
        _, record = service.create_key(
            tenant_id="tenant-integration-b",
            scopes=("execution:queue",),
        )
        pg_session.flush()
        result = service.authenticate_machine(
            tenant_id="tenant-integration-b",
            key_id=record.key_id,
            plaintext="wrong-plaintext-that-will-not-match",
        )
        assert result is None

    def test_revoked_key_cannot_authenticate(self, pg_session) -> None:
        """A revoked key must not authenticate even with correct plaintext."""
        service = ApiKeyService(pg_session)
        plaintext, record = service.create_key(
            tenant_id="tenant-integration-c",
            scopes=("execution:queue",),
        )
        pg_session.flush()
        service.revoke_key(key_id=record.key_id)
        pg_session.flush()
        result = service.authenticate_machine(
            tenant_id="tenant-integration-c",
            key_id=record.key_id,
            plaintext=plaintext,
        )
        assert result is None

    def test_cross_tenant_isolation(self, pg_session) -> None:
        """A key from tenant-A must not authenticate as tenant-B."""
        service = ApiKeyService(pg_session)
        plaintext, record = service.create_key(
            tenant_id="tenant-isolation-a",
            scopes=("execution:queue",),
        )
        pg_session.flush()
        result = service.authenticate_machine(
            tenant_id="tenant-isolation-b",
            key_id=record.key_id,
            plaintext=plaintext,
        )
        assert result is None

    def test_hash_is_argon2id_not_plaintext(self, pg_session) -> None:
        """The stored hash must be Argon2id, not plaintext."""
        service = ApiKeyService(pg_session)
        plaintext, record = service.create_key(
            tenant_id="tenant-hash-check",
            scopes=("execution:queue",),
        )
        pg_session.flush()
        assert record.key_hash.startswith("$argon2id$"), f"Expected Argon2id hash, got: {record.key_hash[:20]}..."
        assert plaintext not in record.key_hash
