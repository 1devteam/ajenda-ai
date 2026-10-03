from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.domain.outcome_review import OutcomeReview
from backend.services.knowledge.knowledge_change_proposals import build_knowledge_change_proposals
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_state import (
    build_deliverable_runtime_state,
    load_deliverable_runtime_state,
)


def _review(
    *, tenant_id: str, mission_id: uuid.UUID, evidence: list[dict[str, object]], status: str = "completed"
) -> OutcomeReview:
    return OutcomeReview(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        evidence_references=evidence,
        review_status=status,
        review_decision="inconclusive",
        reviewer_type="human",
        reviewer_source="test",
        review_summary="Observed a repeatable terminology mismatch.",
        structured_findings=[
            {
                "knowledge_key": "tenant.gtm.qualification",
                "suggested_change": "Add service-area alias",
                "confidence": 0.8,
            }
        ],
        confidence=0.7,
    )


def test_proposals_are_evidence_backed_and_non_authoritative() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    request = extract_deliverable_request("Return company name.")
    assert request is not None
    state = build_deliverable_runtime_state(request)
    assert state is not None
    result = build_knowledge_change_proposals(
        tenant_id=tenant_id,
        mission_id=mission_id,
        reviews=[
            _review(tenant_id=tenant_id, mission_id=mission_id, evidence=[{"evidence_id": "e1", "artifact_id": "a1"}])
        ],
        runtime_state=load_deliverable_runtime_state(state),
        generated_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.scope == "tenant_private"
    assert proposal.source_artifact_ids == ("a1",)
    assert proposal.grants_execution_authority is False
    assert proposal.authority_class == "read_model"


def test_proposals_skip_missing_evidence_rejected_and_foreign_reviews() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    result = build_knowledge_change_proposals(
        tenant_id=tenant_id,
        mission_id=mission_id,
        reviews=[
            _review(tenant_id=tenant_id, mission_id=mission_id, evidence=[]),
            _review(tenant_id=tenant_id, mission_id=mission_id, evidence=[{"evidence_id": "e2"}], status="draft"),
            _review(tenant_id=str(uuid.uuid4()), mission_id=mission_id, evidence=[{"evidence_id": "e3"}]),
        ],
        runtime_state=None,
    )
    assert result.proposals == ()


def test_shared_candidate_remains_review_only() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    review = _review(tenant_id=tenant_id, mission_id=mission_id, evidence=[{"evidence_id": "e4"}])
    review.structured_findings = [{"scope": "shared_candidate", "suggested_change": "Review shared alias"}]
    result = build_knowledge_change_proposals(
        tenant_id=tenant_id, mission_id=mission_id, reviews=[review], runtime_state=None
    )
    assert result.proposals[0].scope == "shared_candidate"
    assert result.proposals[0].status == "review_required"
