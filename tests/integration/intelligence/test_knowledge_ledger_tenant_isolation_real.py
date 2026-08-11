from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.services.knowledge import (
    KnowledgeLedgerIntegrityError,
    KnowledgeLedgerWriteStatus,
    record_knowledge_qualification,
)
from backend.services.ontology.experience_intelligence import RecurrenceStrength
from backend.services.ontology.knowledge_qualification import (
    KnowledgeQualificationResult,
    QualifiedKnowledgeArtifact,
    qualify_pattern_knowledge,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from tests.unit.ontology.test_knowledge_qualification import candidate

pytestmark = pytest.mark.integration


def _tenant() -> str:
    return f"tenant-{uuid.uuid4()}"


def _count(
    session: Session, model: type[KnowledgeQualificationRecord] | type[KnowledgeArtifactRecord], tenant: str
) -> int:
    return session.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant)) or 0


def test_real_qualification_to_tenant_ledger_is_idempotent_and_staged(pg_session) -> None:
    tenant = _tenant()
    result = qualify_pattern_knowledge(candidate())
    original_artifact = result.qualified_knowledge.model_dump(mode="json")

    activate_tenant_session(pg_session, tenant)
    first = record_knowledge_qualification(pg_session, tenant_id=tenant, result=result)
    replay = record_knowledge_qualification(pg_session, tenant_id=tenant, result=result)

    assert first.status == KnowledgeLedgerWriteStatus.RECORDED
    assert first.persistence_committed is False
    assert replay.status == KnowledgeLedgerWriteStatus.ALREADY_RECORDED
    assert replay.persistence_committed is False
    assert replay.qualification_record_id == first.qualification_record_id
    assert replay.artifact_record_id == first.artifact_record_id
    assert result.qualified_knowledge.model_dump(mode="json") == original_artifact
    assert result.qualified_knowledge.is_persisted is False

    qualification = pg_session.scalar(
        select(KnowledgeQualificationRecord).where(
            KnowledgeQualificationRecord.id == first.qualification_record_id,
            KnowledgeQualificationRecord.tenant_id == tenant,
        )
    )
    artifact = pg_session.scalar(
        select(KnowledgeArtifactRecord).where(
            KnowledgeArtifactRecord.id == first.artifact_record_id,
            KnowledgeArtifactRecord.tenant_id == tenant,
        )
    )
    assert qualification is not None and artifact is not None
    assert qualification.proposition_key == result.proposition.proposition_key
    assert qualification.qualification_id == result.qualification_id
    assert artifact.knowledge_id == result.qualified_knowledge.knowledge_id
    assert artifact.qualification_record_id == qualification.id
    KnowledgeQualificationResult.model_validate(qualification.qualification_payload)
    QualifiedKnowledgeArtifact.model_validate(artifact.artifact_payload)


def test_cross_tenant_identical_semantic_identities_create_independent_rows(pg_session) -> None:
    first_tenant, second_tenant = _tenant(), _tenant()
    result = qualify_pattern_knowledge(candidate())

    activate_tenant_session(pg_session, first_tenant)
    first = record_knowledge_qualification(pg_session, tenant_id=first_tenant, result=result)
    activate_tenant_session(pg_session, second_tenant)
    second = record_knowledge_qualification(pg_session, tenant_id=second_tenant, result=result)

    assert second.qualification_record_id != first.qualification_record_id
    assert second.artifact_record_id != first.artifact_record_id
    assert _count(pg_session, KnowledgeQualificationRecord, first_tenant) == 1
    assert _count(pg_session, KnowledgeQualificationRecord, second_tenant) == 1


def test_qualification_identity_collision_fails_closed(pg_session) -> None:
    tenant = _tenant()
    result = qualify_pattern_knowledge(candidate())
    conflicting = result.model_copy(update={"epistemic_limits": (*result.epistemic_limits, "collision")})
    activate_tenant_session(pg_session, tenant)
    record_knowledge_qualification(pg_session, tenant_id=tenant, result=result)

    with pytest.raises(KnowledgeLedgerIntegrityError, match="qualification identity"):
        record_knowledge_qualification(pg_session, tenant_id=tenant, result=conflicting)


def test_knowledge_identity_collision_fails_closed(pg_session) -> None:
    tenant = _tenant()
    result = qualify_pattern_knowledge(candidate())
    second_qualification_id = f"{result.qualification_id}-second-assessment"
    conflicting_artifact = result.qualified_knowledge.model_copy(update={"qualification_id": second_qualification_id})
    conflicting = result.model_copy(
        update={
            "qualification_id": second_qualification_id,
            "qualified_knowledge": conflicting_artifact,
        }
    )
    activate_tenant_session(pg_session, tenant)
    record_knowledge_qualification(pg_session, tenant_id=tenant, result=result)

    with pytest.raises(KnowledgeLedgerIntegrityError, match="different canonical payload"):
        record_knowledge_qualification(pg_session, tenant_id=tenant, result=conflicting)


@pytest.mark.parametrize(
    "strength",
    (
        RecurrenceStrength.EMERGING,
        RecurrenceStrength.CONTESTED,
        RecurrenceStrength.INVALIDATED,
        RecurrenceStrength.WEAK,
    ),
)
def test_proposition_bearing_nonqualified_statuses_record_history_only(pg_session, strength) -> None:
    tenant = _tenant()
    result = qualify_pattern_knowledge(candidate(strength=strength))
    assert result.proposition is not None
    assert result.qualified_knowledge is None
    activate_tenant_session(pg_session, tenant)

    write = record_knowledge_qualification(pg_session, tenant_id=tenant, result=result)

    assert write.qualification_created is True
    assert write.artifact_created is False
    assert _count(pg_session, KnowledgeQualificationRecord, tenant) == 1
    assert _count(pg_session, KnowledgeArtifactRecord, tenant) == 0


def test_propositionless_result_creates_zero_rows(pg_session) -> None:
    tenant = _tenant()
    result = qualify_pattern_knowledge(candidate().model_copy(update={"semantic_context": None}))
    activate_tenant_session(pg_session, tenant)

    write = record_knowledge_qualification(pg_session, tenant_id=tenant, result=result)

    assert write.status == KnowledgeLedgerWriteStatus.NOT_LEDGER_ELIGIBLE
    assert write.persistence_committed is False
    assert _count(pg_session, KnowledgeQualificationRecord, tenant) == 0
    assert _count(pg_session, KnowledgeArtifactRecord, tenant) == 0


def test_artifact_collision_rolls_back_new_qualification_through_action(pg_engine) -> None:
    tenant = _tenant()
    result = qualify_pattern_knowledge(candidate())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        activate_tenant_session(setup, tenant)
        record_knowledge_qualification(setup, tenant_id=tenant, result=result)
        setup.commit()

    second_qualification_id = f"{result.qualification_id}-atomicity"
    conflicting = result.model_copy(
        update={
            "qualification_id": second_qualification_id,
            "qualified_knowledge": result.qualified_knowledge.model_copy(
                update={"qualification_id": second_qualification_id}
            ),
        }
    )
    invocation = ToolInvocation(
        action="knowledge.record_qualification",
        input={"result": conflicting.model_dump(mode="json")},
    )
    context = ActionRuntimeContext(
        tenant_id=tenant,
        task_id=uuid.uuid4(),
        worker_id="worker",
        lease_id="lease",
        session_factory=factory,
    )

    with pytest.raises(KnowledgeLedgerIntegrityError):
        get_default_action_registry(rebuild=True).invoke(invocation, context)

    with factory() as verification:
        activate_tenant_session(verification, tenant)
        qualification_ids = set(
            verification.scalars(
                select(KnowledgeQualificationRecord.qualification_id).where(
                    KnowledgeQualificationRecord.tenant_id == tenant
                )
            )
        )
        assert qualification_ids == {result.qualification_id}
        assert _count(verification, KnowledgeArtifactRecord, tenant) == 1


def test_late_older_evaluation_watermark_appends_without_replacement(pg_session) -> None:
    tenant = _tenant()
    newer = qualify_pattern_knowledge(candidate(latest=datetime(2026, 2, 1, tzinfo=UTC)))
    older = qualify_pattern_knowledge(
        candidate(
            support=("ep-1", "ep-2", "ep-3", "ep-older"),
            latest=datetime(2026, 1, 4, tzinfo=UTC),
        )
    )
    assert newer.proposition.proposition_key == older.proposition.proposition_key
    assert newer.qualification_id != older.qualification_id
    activate_tenant_session(pg_session, tenant)

    newest_write = record_knowledge_qualification(pg_session, tenant_id=tenant, result=newer)
    older_write = record_knowledge_qualification(pg_session, tenant_id=tenant, result=older)

    rows = list(
        pg_session.scalars(
            select(KnowledgeQualificationRecord)
            .where(KnowledgeQualificationRecord.tenant_id == tenant)
            .order_by(KnowledgeQualificationRecord.evaluation_watermark)
        )
    )
    assert len(rows) == 2
    assert rows[0].id == older_write.qualification_record_id
    assert rows[1].id == newest_write.qualification_record_id


def test_rls_hides_other_tenants_and_unset_context_fails_closed(pg_engine) -> None:
    role = f"knowledge_ledger_test_{uuid.uuid4().hex}"
    tenant_a, tenant_b = _tenant(), _tenant()
    result = qualify_pattern_knowledge(candidate())
    quoted_role = f'"{role}"'
    with pg_engine.begin() as admin:
        admin.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))
        admin.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
        admin.execute(
            text(
                f"GRANT SELECT, INSERT ON knowledge_qualification_records, knowledge_artifact_records TO {quoted_role}"
            )
        )
    try:
        with pg_engine.connect() as connection:
            connection.execute(text(f"SET ROLE {quoted_role}"))
            session = Session(bind=connection, expire_on_commit=False)
            activate_tenant_session(session, tenant_a)
            record_knowledge_qualification(session, tenant_id=tenant_a, result=result)
            session.commit()

            activate_tenant_session(session, tenant_b)
            assert _count(session, KnowledgeQualificationRecord, tenant_a) == 0
            assert _count(session, KnowledgeArtifactRecord, tenant_a) == 0

            session.execute(text("RESET app.current_tenant_id"))
            assert _count(session, KnowledgeQualificationRecord, tenant_a) == 0
            with pytest.raises(DBAPIError):
                record_knowledge_qualification(session, tenant_id=tenant_b, result=result)
            session.rollback()
            session.close()
            connection.execute(text("RESET ROLE"))
            connection.commit()
    finally:
        with pg_engine.begin() as admin:
            admin.execute(text(f"DROP OWNED BY {quoted_role}"))
            admin.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))
