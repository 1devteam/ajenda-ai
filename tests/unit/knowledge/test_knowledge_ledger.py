from __future__ import annotations

import uuid
from unittest.mock import Mock

from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.repositories.knowledge_repository import AppendResult
from backend.services.knowledge import KnowledgeLedgerWriteStatus, record_knowledge_qualification
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from tests.unit.ontology.test_knowledge_qualification import candidate


def test_direct_service_write_is_staged_until_its_caller_commits(monkeypatch) -> None:
    result = qualify_pattern_knowledge(candidate())
    qualification_record_id = uuid.uuid4()
    artifact_record_id = uuid.uuid4()

    class RepositoryStub:
        def __init__(self, session) -> None:
            assert session is caller_owned_session

        def append_qualification(self, **values) -> AppendResult:
            return AppendResult(
                record=KnowledgeQualificationRecord(id=qualification_record_id, **values),
                created=True,
            )

        def append_artifact(self, **values) -> AppendResult:
            return AppendResult(
                record=KnowledgeArtifactRecord(id=artifact_record_id, **values),
                created=True,
            )

    caller_owned_session = Mock()
    monkeypatch.setattr(
        "backend.services.knowledge.knowledge_ledger.KnowledgeRepository",
        RepositoryStub,
    )

    write = record_knowledge_qualification(
        caller_owned_session,
        tenant_id="tenant-A",
        result=result,
    )

    assert write.status == KnowledgeLedgerWriteStatus.RECORDED
    assert write.qualification_record_id == qualification_record_id
    assert write.artifact_record_id == artifact_record_id
    assert write.persistence_committed is False
    caller_owned_session.commit.assert_not_called()
