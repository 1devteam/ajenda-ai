"""Governed owner for applying accepted tenant-private knowledge proposals."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.domain.business_profile import BusinessProfile
from backend.domain.knowledge_change_proposal import KnowledgeChangeProposalRecord
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.knowledge_change_proposal_repository import KnowledgeChangeProposalRepository


class TenantKnowledgeApplicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    proposal_id: str
    tenant_id: str
    profile_id: uuid.UUID
    category: str
    status: str = "applied"
    applied_at: datetime
    grants_execution_authority: bool = False


class TenantKnowledgeApplicationError(ValueError):
    """Proposal cannot be applied under the tenant-private authority boundary."""


class TenantKnowledgeApplicationService:
    """Apply only explicit, accepted tenant-private facts to the tenant profile."""

    def apply(
        self,
        session: Session,
        *,
        proposal: KnowledgeChangeProposalRecord,
        profile: BusinessProfile,
        approved_fact: dict[str, Any],
        actor_id: str,
        note: str,
    ) -> TenantKnowledgeApplicationResult:
        if proposal.scope != "tenant_private":
            raise TenantKnowledgeApplicationError("shared knowledge candidates cannot be applied by a tenant")
        if proposal.status != "accepted":
            raise TenantKnowledgeApplicationError("only accepted proposals can be applied")
        if proposal.tenant_id != profile.tenant_id:
            raise TenantKnowledgeApplicationError("proposal and profile tenants do not match")
        if profile.status != "active":
            raise TenantKnowledgeApplicationError("only active tenant profiles can receive knowledge")
        if not approved_fact:
            raise TenantKnowledgeApplicationError("approved_fact must be a non-empty structured object")
        if not note.strip():
            raise TenantKnowledgeApplicationError("application note is required")

        provenance = dict(proposal.provenance or {})
        accepted_fact = provenance.get("accepted_fact")
        accepted_fact_hash = provenance.get("accepted_fact_sha256")
        if not isinstance(accepted_fact, dict) or not accepted_fact:
            raise TenantKnowledgeApplicationError("accepted proposal is missing its bound fact payload")
        expected_hash = hashlib.sha256(
            json.dumps(accepted_fact, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if accepted_fact_hash != expected_hash:
            raise TenantKnowledgeApplicationError("accepted proposal fact binding is invalid")
        submitted_hash = hashlib.sha256(
            json.dumps(approved_fact, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if submitted_hash != expected_hash or approved_fact != accepted_fact:
            raise TenantKnowledgeApplicationError("approved_fact does not match the accepted proposal payload")

        applied_at = datetime.now(UTC)
        BusinessProfileRepository(session).upsert_approved_fact(
            profile=profile,
            category=proposal.target_key,
            approved_fact=approved_fact,
            actor_id=actor_id,
            updated_at=applied_at,
            provenance_metadata={
                "knowledge_change_proposal_id": proposal.proposal_id,
                "review_id": str(proposal.review_id),
                "source_artifact_ids": list(proposal.source_artifact_ids or []),
                "application_note": note,
                "accepted_fact_sha256": expected_hash,
            },
        )
        KnowledgeChangeProposalRepository(session).transition(
            record=proposal,
            status="applied",
            actor_id=actor_id,
            provenance={"application_note": note, "applied_at": applied_at.isoformat()},
        )
        AuditEventRepository(session).append(
            AuditEvent(
                tenant_id=proposal.tenant_id,
                mission_id=proposal.mission_id,
                category="knowledge_change_proposal",
                action="applied_to_tenant_profile",
                actor=actor_id,
                details=note,
                payload_json={
                    "proposal_id": proposal.proposal_id,
                    "profile_id": str(profile.id),
                    "category": proposal.target_key,
                },
            )
        )
        return TenantKnowledgeApplicationResult(
            proposal_id=proposal.proposal_id,
            tenant_id=proposal.tenant_id,
            profile_id=profile.id,
            category=proposal.target_key,
            applied_at=applied_at,
        )
