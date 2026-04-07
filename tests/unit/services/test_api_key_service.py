"""Unit tests for ApiKeyService.

Uses an in-memory SQLite database via SQLAlchemy. JSONB columns are
overridden to use JSON for SQLite compatibility (JSONB is Postgres-only).
"""

from __future__ import annotations

import pytest
from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, sessionmaker

from backend.db.base import Base
from backend.services.api_key_service import ApiKeyService


def _sqlite_session() -> Session:
    """Create an in-memory SQLite session with JSONB columns remapped to JSON."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    # Override JSONB -> JSON for SQLite compatibility
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    # Remap JSONB columns to JSON for SQLite
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return factory()


def test_api_key_service_create_and_authenticate() -> None:
    """ApiKeyService creates a key and authenticates it correctly."""
    session = _sqlite_session()
    service = ApiKeyService(session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=("execution:queue",))
    session.commit()
    principal = service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)
    assert principal.tenant_id == "tenant-a"


def test_api_key_service_rejects_revoked_key() -> None:
    """ApiKeyService raises ValueError when authenticating a revoked key."""
    session = _sqlite_session()
    service = ApiKeyService(session)
    plaintext, record = service.create_key(tenant_id="tenant-a", scopes=())
    session.commit()
    service.revoke_key(key_id=record.key_id)
    session.commit()
    with pytest.raises(ValueError):
        service.authenticate_machine(tenant_id="tenant-a", key_id=record.key_id, plaintext=plaintext)


def test_api_key_service_count_active_keys() -> None:
    """count_active_keys returns the correct count for a tenant."""
    session = _sqlite_session()
    service = ApiKeyService(session)
    service.create_key(tenant_id="tenant-a", scopes=())
    service.create_key(tenant_id="tenant-a", scopes=())
    service.create_key(tenant_id="tenant-b", scopes=())
    session.commit()
    assert service.count_active_keys(tenant_id="tenant-a") == 2
    assert service.count_active_keys(tenant_id="tenant-b") == 1
