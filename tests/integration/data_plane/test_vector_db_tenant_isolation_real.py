"""Tenant isolation for ephemeral memory chunks on the vector data plane."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.ephemeral_memory_chunk_repository import EphemeralMemoryChunkRepository

pytestmark = pytest.mark.integration


def test_ephemeral_memory_chunks_are_tenant_isolated_under_rls(pg_engine) -> None:
    tenant_a = f"tenant-a-{uuid.uuid4().hex[:8]}"
    tenant_b = f"tenant-b-{uuid.uuid4().hex[:8]}"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session_a = session_factory()
    session_b = session_factory()
    try:
        activate_tenant_session(session_a, tenant_a)
        activate_tenant_session(session_b, tenant_b)

        repo_a = EphemeralMemoryChunkRepository(session_a)
        repo_b = EphemeralMemoryChunkRepository(session_b)

        repo_a.upsert_chunk(
            tenant_id=tenant_a,
            content="Tenant A roofing memory",
            chunk_id="chunk-a",
        )
        repo_b.upsert_chunk(
            tenant_id=tenant_b,
            content="Tenant B roofing memory",
            chunk_id="chunk-b",
        )
        session_a.commit()
        session_b.commit()

        tenant_a_hits = repo_a.keyword_search(tenant_id=tenant_a, query="roofing", limit=5)
        tenant_b_hits = repo_b.keyword_search(tenant_id=tenant_b, query="roofing", limit=5)

        assert [item["id"] for item in tenant_a_hits] == ["chunk-a"]
        assert [item["id"] for item in tenant_b_hits] == ["chunk-b"]
    finally:
        session_a.close()
        session_b.close()
