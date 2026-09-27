"""Real retrieval.hybrid_search through the action registry and vector data plane."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.repositories.ephemeral_memory_chunk_repository import EphemeralMemoryChunkRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation

pytestmark = pytest.mark.integration


def test_retrieval_hybrid_search_merges_internal_records_and_ephemeral_chunks(pg_engine) -> None:
    tenant_id = f"tenant-retrieval-{uuid.uuid4().hex[:8]}"
    mission_id = uuid.uuid4()
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    session = session_factory()
    try:
        activate_tenant_session(session, tenant_id)
        internal_repo = TenantInternalRecordRepository(session)
        internal_repo.write_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id="acct-roofing",
            data={"name": "Austin Roofing Co", "city": "Austin"},
        )
        memory_repo = EphemeralMemoryChunkRepository(session)
        memory_repo.upsert_chunk(
            tenant_id=tenant_id,
            content="Approved Austin roofing outreach playbook",
            mission_id=str(mission_id),
            chunk_id="chunk-roofing",
        )
        session.commit()
    finally:
        session.close()

    registry = get_default_action_registry(rebuild=True)
    invocation = ToolInvocation(
        action="retrieval.hybrid_search",
        input={"query": "Austin roofing", "mission_id": str(mission_id), "limit": 5},
    )
    context = ActionRuntimeContext(
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        mission_id=mission_id,
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=session_factory,
        vector_session_factory=session_factory,
    )
    result = registry.invoke(invocation, context)
    repeated = registry.invoke(invocation, context)

    assert result.output["real"] is True
    assert result.output["plugin_required"] is False
    assert result.output["source"] == "ajenda_brain"
    memory_ids = {str(item.get("id")) for item in result.output["memories"]}
    assert "mem1" not in memory_ids
    assert "mem2" not in memory_ids
    assert "chunk-roofing" in memory_ids or any(
        "Austin" in str(item.get("content")) for item in result.output["memories"]
    )
    assert [item["id"] for item in result.output["memory_hits"]] == [
        item["id"] for item in repeated.output["memory_hits"]
    ]
