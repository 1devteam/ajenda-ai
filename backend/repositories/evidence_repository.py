from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.evidence import EvidenceRecord


class EvidenceRepository:
    """Persistence contract for tenant-owned evidence records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, evidence: EvidenceRecord) -> EvidenceRecord:
        self._session.add(evidence)
        self._session.flush()
        self._session.refresh(evidence)
        return evidence

    def get_for_tenant(self, *, evidence_id: uuid.UUID, tenant_id: str) -> EvidenceRecord | None:
        stmt = select(EvidenceRecord).where(EvidenceRecord.id == evidence_id, EvidenceRecord.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def list_for_mission(self, *, mission_id: uuid.UUID, tenant_id: str) -> list[EvidenceRecord]:
        stmt = (
            select(EvidenceRecord)
            .where(EvidenceRecord.mission_id == mission_id, EvidenceRecord.tenant_id == tenant_id)
            .order_by(EvidenceRecord.created_at.asc())
        )
        return list(self._session.scalars(stmt))

    def update(self, evidence: EvidenceRecord) -> EvidenceRecord:
        self._session.add(evidence)
        self._session.flush()
        self._session.refresh(evidence)
        return evidence
