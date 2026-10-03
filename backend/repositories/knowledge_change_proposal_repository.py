from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.knowledge_change_proposal import KnowledgeChangeProposalRecord


class KnowledgeChangeProposalRepository:
    """Tenant-scoped persistence and lifecycle transitions for proposals."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, *, tenant_id: str, proposal_id: str) -> KnowledgeChangeProposalRecord | None:
        return self._session.scalar(
            select(KnowledgeChangeProposalRecord).where(
                KnowledgeChangeProposalRecord.tenant_id == tenant_id,
                KnowledgeChangeProposalRecord.proposal_id == proposal_id,
            )
        )

    def list_for_mission(self, *, tenant_id: str, mission_id: uuid.UUID) -> list[KnowledgeChangeProposalRecord]:
        stmt = (
            select(KnowledgeChangeProposalRecord)
            .where(
                KnowledgeChangeProposalRecord.tenant_id == tenant_id,
                KnowledgeChangeProposalRecord.mission_id == mission_id,
            )
            .order_by(KnowledgeChangeProposalRecord.created_at.asc())
        )
        return list(self._session.scalars(stmt))

    def add(self, record: KnowledgeChangeProposalRecord) -> KnowledgeChangeProposalRecord:
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return record

    def transition(
        self,
        *,
        record: KnowledgeChangeProposalRecord,
        status: str,
        actor_id: str,
        provenance: dict[str, Any],
        superseded_by_proposal_id: str | None = None,
        rollback_of_proposal_id: str | None = None,
    ) -> KnowledgeChangeProposalRecord:
        record.status = status
        record.superseded_by_proposal_id = superseded_by_proposal_id
        record.rollback_of_proposal_id = rollback_of_proposal_id
        record.provenance = {**dict(record.provenance or {}), **provenance, "last_actor_id": actor_id}
        record.updated_at = datetime.now(UTC)
        self._session.add(record)
        self._session.flush()
        return record
