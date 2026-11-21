"""Tenant-explicit candidate discovery for durable Decision Learning Signals."""

from __future__ import annotations

from sqlalchemy import String, cast, select
from sqlalchemy.orm import Session

from backend.domain.evidence import EvidenceRecord
from backend.domain.lineage_record import LineageRecord

MATERIALIZATION_ACTION = "analysis.materialize_decision_learning_signal"


class DurableLearningSignalRepository:
    """Read-only, tenant-wide evidence query; semantic acceptance is service-owned."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_candidates_for_tenant(self, *, tenant_id: str) -> list[EvidenceRecord]:
        """Select worker projections linked to task-output lineage for this tenant."""

        statement = (
            select(EvidenceRecord)
            .join(
                LineageRecord,
                (cast(LineageRecord.id, String) == EvidenceRecord.materialization_reference["lineage_record_id"].astext)
                & (LineageRecord.task_id == EvidenceRecord.execution_task_id)
                & (LineageRecord.tenant_id == EvidenceRecord.tenant_id),
            )
            .where(
                EvidenceRecord.tenant_id == tenant_id,
                LineageRecord.relationship_type == "task_output",
                EvidenceRecord.materialization_reference["source"].astext == "tool.invoke.task_output",
                EvidenceRecord.materialization_reference["action"].astext == MATERIALIZATION_ACTION,
            )
            .order_by(EvidenceRecord.id)
        )
        return list(self._session.scalars(statement))
