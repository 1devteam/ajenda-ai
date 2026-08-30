from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation


def _context(*, session_factory: object | None = None) -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-retrieval",
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker-1",
        lease_id="lease-1",
        session_factory=session_factory,
    )


def test_retrieval_hybrid_search_returns_real_brain_output_without_mock_memories() -> None:
    registry = get_default_action_registry(rebuild=True)
    internal_hits = [{"id": "acct-1", "name": "Acme Roofing"}]
    keyword_hits = [{"id": "emc-1", "content": "Approved Austin roofing outreach", "search_mode": "keyword"}]
    vector_hits = [{"id": "emc-2", "content": "Austin contractor lead notes", "search_mode": "vector"}]

    with (
        patch(
            "backend.services.tools.retrieval_actions.resolve_record_store",
        ) as record_store_resolver,
        patch(
            "backend.services.tools.retrieval_actions.resolve_memory_chunk_store",
        ) as memory_store_resolver,
    ):
        record_store = MagicMock()
        record_store.search_records.return_value = internal_hits
        record_store_resolver.return_value = record_store

        memory_store = MagicMock()
        memory_store.keyword_search.return_value = keyword_hits
        memory_store.vector_search.return_value = vector_hits
        memory_store_resolver.return_value = memory_store

        result = registry.invoke(
            ToolInvocation(
                action="retrieval.hybrid_search",
                input={"query": "Austin roofing", "limit": 5},
            ),
            _context(),
        )

    assert result.provider == "local_retrieval"
    assert result.output["real"] is True
    assert result.output["plugin_required"] is False
    assert result.output["source"] == "ajenda_brain"
    assert result.output["memory_hits"] == result.output["memories"]
    memory_ids = {item["id"] for item in result.output["memory_hits"]}
    assert "mem1" not in memory_ids
    assert "mem2" not in memory_ids
    assert "emc-1" in memory_ids or "emc-2" in memory_ids or "acct-1" in memory_ids
    assert "keyword" in result.output["search_modes"] or "vector" in result.output["search_modes"]


def test_retrieval_hybrid_search_includes_retrieval_contracts_when_mission_scoped() -> None:
    registry = get_default_action_registry(rebuild=True)
    mission_id = uuid.uuid4()
    contract = MagicMock()
    contract.id = uuid.uuid4()
    contract.retrieval_strategy = "hybrid"
    contract.retrieval_reason = "Need prior mission memory."
    contract.governance_constraints = {"memory_type": "lesson"}
    contract.trust_signal = "approved"
    contract.provenance_metadata = {"source": "mission"}
    contract.retrieval_status = "fulfilled"
    contract.returned_memory_references = [{"memory_id": "contract-mem-1", "summary": "Prior lesson"}]
    contract.memory_references = []

    session = MagicMock()
    session_factory = MagicMock(return_value=session)
    repo = MagicMock()
    repo.list_for_mission.return_value = [contract]

    with (
        patch("backend.services.tools.retrieval_actions.resolve_record_store") as record_store_resolver,
        patch("backend.services.tools.retrieval_actions.resolve_memory_chunk_store") as memory_store_resolver,
        patch(
            "backend.services.tools.retrieval_actions.RetrievalContractRepository",
            return_value=repo,
        ),
    ):
        record_store_resolver.return_value = MagicMock(search_records=MagicMock(return_value=[]))
        memory_store = MagicMock()
        memory_store.keyword_search.return_value = []
        memory_store.vector_search.return_value = []
        memory_store_resolver.return_value = memory_store

        result = registry.invoke(
            ToolInvocation(
                action="retrieval.hybrid_search",
                input={"query": "lesson", "mission_id": str(mission_id), "limit": 5},
            ),
            _context(session_factory=session_factory),
        )

    session.close.assert_called_once()
    assert len(result.output["retrieval_contracts"]) == 1
    assert result.output["retrieval_contracts"][0]["strategy"] == "hybrid"
    contract_ids = result.evidence[0].provenance.get("retrieval_contract_ids", [])
    assert contract_ids == [str(contract.id)]
