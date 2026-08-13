"""Tenant-explicit candidate discovery for durable Decision Learning Signals."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.domain.evidence import EvidenceRecord

MATERIALIZATION_ACTION = "analysis.materialize_decision_learning_signal"


class DurableLearningSignalRepository:
    """Read-only, tenant-wide evidence query; semantic acceptance is service-owned."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_candidates_for_tenant(self, *, tenant_id: str) -> list[EvidenceRecord]:
        """Over-select action-matching records with an explicit tenant predicate."""

        statement = (
            select(EvidenceRecord)
            .where(
                EvidenceRecord.tenant_id == tenant_id,
                or_(
                    EvidenceRecord.provenance_metadata["action_name"].astext == MATERIALIZATION_ACTION,
                    EvidenceRecord.materialization_reference["action"].astext == MATERIALIZATION_ACTION,
                ),
            )
            .order_by(EvidenceRecord.id)
        )
        return list(self._session.scalars(statement))
