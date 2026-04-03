"""Unit tests for ApiKeyService.

Uses an in-memory SQLite DB for speed. SQLite does not support PostgreSQL's
JSONB type, so we patch it with the generic JSON type for unit tests.
Integration tests use a real PostgreSQL container via testcontainers.
"""
from __future__ import annotations
import pytest
from unittest.mock import patch
from sqlalchemy import create_engine, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, sessionmaker
from backend.db.base import Base
from backend.services.api_key_service import ApiKeyService


def _session() -> Session:
    """Create an in-memory SQLite session with JSONB patched to JSON."""
    # JSONB is PostgreSQL-specific; patch it to generic JSON for SQLite unit tests.
    with patch.object(JSONB, "__class_getitem__", return_value=JSON):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
        )
        # Patch JSONB columns to use JSON for SQLite compatibility
        for table in Base.metadata.tables.values():
            for col in table.columns:
                if isinstance(col.type, JSONB):
                    col.type = JSON()
        Base.metadata.create_all(engine)
        return sessionmaker(
            bind=engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )()


def test_api_key_service_create_and_authenticate() -> None:
    """ApiKeyService creates a key and authenticates it correctly."""
    session = _session()
    service = ApiKeyService(session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=("execution:queue",))
    principal = service.authenticate_machine(
        tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext
    )
    assert principal.tenant_id == "tenant-a"


def test_api_key_service_rejects_revoked_key() -> None:
    """ApiKeyService rejects authentication with a revoked key."""
    session = _session()
    service = ApiKeyService(session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    service.revoke_key(key_id=record.key_id)
    with pytest.raises(ValueError):
        service.authenticate_machine(
            tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext
        )
