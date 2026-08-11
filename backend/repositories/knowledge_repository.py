from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord


@dataclass(frozen=True, slots=True)
class AppendResult:
    record: KnowledgeQualificationRecord | KnowledgeArtifactRecord
    created: bool


class KnowledgeRepository:
    """Tenant-explicit, append-only SQL mechanics for the knowledge ledger."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_qualification_for_tenant(
        self, *, tenant_id: str, qualification_id: str
    ) -> KnowledgeQualificationRecord | None:
        return self._session.scalar(
            select(KnowledgeQualificationRecord).where(
                KnowledgeQualificationRecord.tenant_id == tenant_id,
                KnowledgeQualificationRecord.qualification_id == qualification_id,
            )
        )

    def get_artifact_for_tenant(self, *, tenant_id: str, knowledge_id: str) -> KnowledgeArtifactRecord | None:
        return self._session.scalar(
            select(KnowledgeArtifactRecord).where(
                KnowledgeArtifactRecord.tenant_id == tenant_id,
                KnowledgeArtifactRecord.knowledge_id == knowledge_id,
            )
        )

    def list_qualifications_for_proposition(
        self, *, tenant_id: str, proposition_key: str
    ) -> list[KnowledgeQualificationRecord]:
        return list(
            self._session.scalars(
                select(KnowledgeQualificationRecord).where(
                    KnowledgeQualificationRecord.tenant_id == tenant_id,
                    KnowledgeQualificationRecord.proposition_key == proposition_key,
                )
            )
        )

    def list_artifacts_for_qualification_ids(
        self, *, tenant_id: str, qualification_ids: Sequence[str]
    ) -> list[KnowledgeArtifactRecord]:
        if not qualification_ids:
            return []
        return list(
            self._session.scalars(
                select(KnowledgeArtifactRecord).where(
                    KnowledgeArtifactRecord.tenant_id == tenant_id,
                    KnowledgeArtifactRecord.qualification_id.in_(tuple(qualification_ids)),
                )
            )
        )

    def append_qualification(self, **values: Any) -> AppendResult:
        record_id = uuid.uuid4()
        returned = self._session.execute(
            insert(KnowledgeQualificationRecord)
            .values(id=record_id, **values)
            .on_conflict_do_nothing(index_elements=["tenant_id", "qualification_id"])
            .returning(KnowledgeQualificationRecord.id)
        ).scalar_one_or_none()
        record = self.get_qualification_for_tenant(
            tenant_id=values["tenant_id"], qualification_id=values["qualification_id"]
        )
        if record is None:
            raise RuntimeError("qualification conflict did not resolve to a tenant-owned row")
        return AppendResult(record=record, created=returned is not None)

    def append_artifact(self, **values: Any) -> AppendResult:
        record_id = uuid.uuid4()
        returned = self._session.execute(
            insert(KnowledgeArtifactRecord)
            .values(id=record_id, **values)
            .on_conflict_do_nothing()
            .returning(KnowledgeArtifactRecord.id)
        ).scalar_one_or_none()
        record = self.get_artifact_for_tenant(tenant_id=values["tenant_id"], knowledge_id=values["knowledge_id"])
        if record is None:
            raise RuntimeError("artifact conflict did not resolve to a tenant-owned row")
        return AppendResult(record=record, created=returned is not None)
