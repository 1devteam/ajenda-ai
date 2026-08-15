"""Real PostgreSQL proof for durable learning history through Knowledge Ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.evidence import EvidenceRecord
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.domain.tenant import Tenant
from backend.services.durable_experience_consolidation import DurableLearningHistoryError
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from tests.integration.intelligence.canonical_decision_runtime import (
    MATERIALIZATION_ACTION,
    materialize_canonical_decision_episode,
)

pytestmark = pytest.mark.integration


def _ledger_counts(factory, tenant_id: str) -> tuple[int, int]:
    with factory() as verify:
        activate_tenant_session(verify, tenant_id)
        return (
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant_id)
            )
            or 0,
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeArtifactRecord)
                .where(KnowledgeArtifactRecord.tenant_id == tenant_id)
            )
            or 0,
        )


def test_real_cross_mission_history_is_canonical_tenant_isolated_and_replayable(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant_a, tenant_b = str(uuid.uuid4()), str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add_all(
            [
                Tenant(
                    id=uuid.UUID(tenant_a), name="Experience tenant", slug=f"experience-{tenant_a[:8]}", plan="free"
                ),
                Tenant(id=uuid.UUID(tenant_b), name="Other tenant", slug=f"other-{tenant_b[:8]}", plan="free"),
            ]
        )
        setup.commit()

    episodes_a = [
        materialize_canonical_decision_episode(
            factory=factory,
            queue_adapter=queue_adapter,
            tenant_id=tenant_a,
            index=index,
        )
        for index in (1, 2, 3)
    ]
    materialize_canonical_decision_episode(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_b,
        index=4,
    )
    assert len({episode.mission_id for episode in episodes_a}) == 3

    context = ActionRuntimeContext(
        tenant_id=tenant_a,
        task_id=uuid.uuid4(),
        worker_id="integration-worker",
        lease_id="integration-lease",
        session_factory=factory,
    )
    invocation = ToolInvocation(action="knowledge.consolidate_learning_history", input={})
    registry = get_default_action_registry(rebuild=True)
    first = registry.invoke(invocation, context)
    replay = registry.invoke(invocation, context)

    assert set(first.output["records_inspected"]) == {
        str(episode.learning_signal_evidence_id) for episode in episodes_a
    }
    earliest = datetime.fromisoformat(
        first.output["experience"]["pattern_candidates"][0]["earliest_evaluated_at"].replace("Z", "+00:00")
    )
    assert earliest == min(episode.learning_signal.evaluated_at for episode in episodes_a)
    assert first.output["qualifications"][0]["qualification"]["status"] == "qualified"
    assert first.output["qualifications"][0]["ledger_write"]["status"] == "recorded"
    assert replay.output["qualifications"][0]["ledger_write"]["status"] == "already_recorded"
    assert _ledger_counts(factory, tenant_a) == (1, 1)
    assert _ledger_counts(factory, tenant_b) == (0, 0)

    forged_id = uuid.uuid4()
    with factory() as setup:
        setup.add(
            EvidenceRecord(
                id=forged_id,
                tenant_id=tenant_a,
                mission_id=episodes_a[0].mission_id,
                evidence_type="execution_trace",
                evidence_source="public_evidence_contract",
                summary="Caller-claimed learning signal",
                structured_payload=episodes_a[0].learning_signal.model_dump(mode="json"),
                provenance_metadata={
                    "action_name": MATERIALIZATION_ACTION,
                    "evidence_role": "decision_learning_signal",
                },
                materialization_reference={"action": MATERIALIZATION_ACTION},
            )
        )
        setup.commit()

    with pytest.raises(DurableLearningHistoryError, match=str(forged_id)):
        registry.invoke(invocation, context)
    assert _ledger_counts(factory, tenant_a) == (1, 1)
