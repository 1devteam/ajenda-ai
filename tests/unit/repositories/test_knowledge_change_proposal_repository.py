from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.knowledge_change_proposal import KnowledgeChangeProposalRecord
from backend.repositories.knowledge_change_proposal_repository import KnowledgeChangeProposalRepository


def test_transition_records_supersession_and_provenance() -> None:
    session = MagicMock()
    record = KnowledgeChangeProposalRecord(
        tenant_id="tenant-a",
        proposal_id="knowledge-change-v1:test",
        mission_id=uuid.uuid4(),
        review_id=uuid.uuid4(),
        scope="tenant_private",
        target_key="tenant.gtm.aliases",
        suggested_change="Add alias",
        rationale="Observed repeatedly",
        evidence_references=[],
        source_artifact_ids=[],
        runtime_reconciliation="aligned",
        provenance={"source": "outcome_review"},
    )
    result = KnowledgeChangeProposalRepository(session).transition(
        record=record,
        status="superseded",
        actor_id="operator-1",
        provenance={"review_note": "Replaced by newer proposal"},
        superseded_by_proposal_id="knowledge-change-v1:new",
    )
    assert result.status == "superseded"
    assert result.superseded_by_proposal_id == "knowledge-change-v1:new"
    assert result.provenance["source"] == "outcome_review"
    assert result.provenance["last_actor_id"] == "operator-1"
    session.flush.assert_called_once()
