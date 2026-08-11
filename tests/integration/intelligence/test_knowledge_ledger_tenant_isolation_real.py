from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.db.tenant_session import activate_tenant_session
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.services.knowledge import KnowledgeLedgerWriteStatus, record_knowledge_qualification
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationResult,
    QualifiedKnowledgeArtifact,
    qualify_pattern_knowledge,
)
from tests.unit.ontology.test_knowledge_qualification import candidate

pytestmark = pytest.mark.integration


def test_real_qualification_to_tenant_ledger_is_idempotent_and_tenant_scoped(pg_session) -> None:
    result = qualify_pattern_knowledge(candidate())
    original_artifact = result.qualified_knowledge.model_dump(mode="json")

    activate_tenant_session(pg_session, "tenant-A")
    first = record_knowledge_qualification(pg_session, tenant_id="tenant-A", result=result)
    replay = record_knowledge_qualification(pg_session, tenant_id="tenant-A", result=result)

    assert first.status == KnowledgeLedgerWriteStatus.RECORDED
    assert replay.status == KnowledgeLedgerWriteStatus.ALREADY_RECORDED
    assert replay.qualification_record_id == first.qualification_record_id
    assert replay.artifact_record_id == first.artifact_record_id
    assert result.qualified_knowledge.model_dump(mode="json") == original_artifact
    assert result.qualified_knowledge.is_persisted is False

    qualification = pg_session.scalar(
        select(KnowledgeQualificationRecord).where(
            KnowledgeQualificationRecord.id == first.qualification_record_id,
            KnowledgeQualificationRecord.tenant_id == "tenant-A",
        )
    )
    artifact = pg_session.scalar(
        select(KnowledgeArtifactRecord).where(
            KnowledgeArtifactRecord.id == first.artifact_record_id,
            KnowledgeArtifactRecord.tenant_id == "tenant-A",
        )
    )
    assert qualification is not None and artifact is not None
    assert qualification.proposition_key == result.proposition.proposition_key
    assert qualification.qualification_id == result.qualification_id
    assert artifact.knowledge_id == result.qualified_knowledge.knowledge_id
    assert artifact.qualification_record_id == qualification.id
    KnowledgeQualificationResult.model_validate(qualification.qualification_payload)
    QualifiedKnowledgeArtifact.model_validate(artifact.artifact_payload)

    activate_tenant_session(pg_session, "tenant-B")
    other = record_knowledge_qualification(pg_session, tenant_id="tenant-B", result=result)
    assert other.qualification_record_id != first.qualification_record_id
    assert other.artifact_record_id != first.artifact_record_id
