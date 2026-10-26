from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.evidence import EvidenceRecord


class EvidenceRepository:
    """Persistence contract for tenant-owned evidence records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, evidence: EvidenceRecord) -> EvidenceRecord:
        # The nullable logical identity is used only by materialized episode
        # evidence.  Its database uniqueness is the concurrency boundary; a
        # retry may return the existing *identical* canonical record, but a
        # contradictory payload must never be silently reconciled.
        if evidence.logical_identity is None:
            self._session.add(evidence)
            self._session.flush()
            self._session.refresh(evidence)
            return evidence
        try:
            with self._session.begin_nested():
                self._session.add(evidence)
                self._session.flush()
        except IntegrityError as exc:
            existing = self._session.scalar(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == evidence.tenant_id,
                    EvidenceRecord.logical_identity == evidence.logical_identity,
                )
            )
            if existing is None or not self._same_logical_evidence(existing=existing, incoming=evidence):
                raise ValueError("logical evidence identity conflicts with an existing canonical record") from exc
            return existing
        self._session.refresh(evidence)
        return evidence

    @staticmethod
    def _same_logical_evidence(*, existing: EvidenceRecord, incoming: EvidenceRecord) -> bool:
        return (
            existing.evidence_type == incoming.evidence_type
            and existing.evidence_source == incoming.evidence_source
            and existing.structured_payload == incoming.structured_payload
            and existing.provenance_metadata.get("action_name") == incoming.provenance_metadata.get("action_name")
            and existing.provenance_metadata.get("evidence_role") == incoming.provenance_metadata.get("evidence_role")
        )

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
