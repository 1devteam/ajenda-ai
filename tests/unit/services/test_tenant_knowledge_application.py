from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.domain.business_profile import BusinessProfile
from backend.domain.knowledge_change_proposal import KnowledgeChangeProposalRecord
from backend.services.knowledge.tenant_knowledge_application import (
    TenantKnowledgeApplicationError,
    TenantKnowledgeApplicationService,
)


def _proposal(*, scope: str = "tenant_private", status: str = "accepted") -> KnowledgeChangeProposalRecord:
    return KnowledgeChangeProposalRecord(
        tenant_id="tenant-a",
        proposal_id="knowledge-change-v1:test",
        mission_id=uuid.uuid4(),
        review_id=uuid.uuid4(),
        scope=scope,
        target_key="tenant.gtm.aliases",
        suggested_change="Add alias",
        rationale="Observed repeatedly",
        evidence_references=[{"evidence_id": "e1"}],
        source_artifact_ids=["artifact-1"],
        runtime_reconciliation="aligned",
        status=status,
    )


def test_application_requires_accepted_tenant_private_proposal(monkeypatch) -> None:
    service = TenantKnowledgeApplicationService()
    session = MagicMock()
    profile = BusinessProfile(id=uuid.uuid4(), tenant_id="tenant-a", status="active")
    for proposal in (_proposal(scope="shared_candidate"), _proposal(status="review_required")):
        with pytest.raises(TenantKnowledgeApplicationError):
            service.apply(
                session,
                proposal=proposal,
                profile=profile,
                approved_fact={"value": "alias"},
                actor_id="operator-1",
                note="approved explicitly",
            )


def test_application_writes_profile_with_provenance_and_audit(monkeypatch) -> None:
    profile_repo = MagicMock()
    proposal_repo = MagicMock()
    audit_repo = MagicMock()
    monkeypatch.setattr(
        "backend.services.knowledge.tenant_knowledge_application.BusinessProfileRepository",
        lambda _session: profile_repo,
    )
    monkeypatch.setattr(
        "backend.services.knowledge.tenant_knowledge_application.KnowledgeChangeProposalRepository",
        lambda _session: proposal_repo,
    )
    monkeypatch.setattr(
        "backend.services.knowledge.tenant_knowledge_application.AuditEventRepository", lambda _session: audit_repo
    )
    session = MagicMock()
    profile = BusinessProfile(id=uuid.uuid4(), tenant_id="tenant-a", status="active")
    result = TenantKnowledgeApplicationService().apply(
        session,
        proposal=_proposal(),
        profile=profile,
        approved_fact={"value": "alias"},
        actor_id="operator-1",
        note="approved explicitly",
    )
    assert result.status == "applied"
    assert result.grants_execution_authority is False
    profile_repo.upsert_approved_fact.assert_called_once()
    proposal_repo.transition.assert_called_once()
    assert proposal_repo.transition.call_args.kwargs["status"] == "applied"
    audit_repo.append.assert_called_once()
