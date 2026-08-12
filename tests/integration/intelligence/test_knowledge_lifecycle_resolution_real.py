from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.services.ontology.experience_intelligence import RecurrenceStrength
from backend.services.ontology.knowledge_qualification import qualify_pattern_knowledge
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from tests.unit.ontology.test_knowledge_qualification import candidate

pytestmark = pytest.mark.integration


def _context(tenant: str, factory) -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id=tenant,
        task_id=uuid.uuid4(),
        worker_id="worker",
        lease_id="lease",
        session_factory=factory,
    )


def test_real_ledger_to_current_state_is_read_only_and_tenant_scoped(pg_engine) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other_tenant = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)
    provisional = qualify_pattern_knowledge(
        candidate(strength=RecurrenceStrength.EMERGING, latest=datetime(2026, 1, 1, tzinfo=UTC))
    )
    qualified = qualify_pattern_knowledge(candidate(latest=datetime(2026, 2, 1, tzinfo=UTC)))
    assert provisional.proposition.proposition_key == qualified.proposition.proposition_key

    for result in (provisional, qualified):
        registry.invoke(
            ToolInvocation(action="knowledge.record_qualification", input={"result": result.model_dump(mode="json")}),
            _context(tenant, factory),
        )

    with factory() as session:
        activate_tenant_session(session, tenant)
        before = (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant)
            ),
            session.scalar(
                select(func.count())
                .select_from(KnowledgeArtifactRecord)
                .where(KnowledgeArtifactRecord.tenant_id == tenant)
            ),
        )

    resolved = registry.invoke(
        ToolInvocation(
            action="knowledge.resolve_current_state",
            input={"proposition_key": qualified.proposition.proposition_key},
        ),
        _context(tenant, factory),
    )
    assert resolved.output["lifecycle_status"] == "active"
    assert resolved.output["evaluation_frontier"] == "2026-02-01T00:00:00Z"
    assert resolved.output["authoritative_qualification_ids"] == [qualified.qualification_id]
    assert resolved.output["authoritative_knowledge_ids"] == [qualified.qualified_knowledge.knowledge_id]
    assert resolved.output["historical_qualification_count"] == 2

    hidden = registry.invoke(
        ToolInvocation(
            action="knowledge.resolve_current_state",
            input={"proposition_key": qualified.proposition.proposition_key},
        ),
        _context(other_tenant, factory),
    )
    assert hidden.output["lifecycle_status"] == "absent"
    assert hidden.output["historical_qualification_count"] == 0

    with factory() as session:
        activate_tenant_session(session, tenant)
        after = (
            session.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant)
            ),
            session.scalar(
                select(func.count())
                .select_from(KnowledgeArtifactRecord)
                .where(KnowledgeArtifactRecord.tenant_id == tenant)
            ),
        )
    assert after == before == (2, 1)
