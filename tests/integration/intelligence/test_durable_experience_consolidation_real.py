"""Real PostgreSQL proof for durable learning history through Knowledge Ledger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.evidence import EvidenceRecord
from backend.domain.knowledge import KnowledgeArtifactRecord, KnowledgeQualificationRecord
from backend.domain.mission import Mission
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from tests.unit.services.test_durable_experience_consolidation import canonical_signal

pytestmark = pytest.mark.integration


def test_real_cross_mission_history_is_tenant_isolated_late_arrival_safe_and_replayable(pg_engine) -> None:
    tenant_a, tenant_b = f"tenant-{uuid.uuid4()}", f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    evaluated = datetime(2026, 8, 12, 9, tzinfo=UTC)

    with factory() as setup:
        for tenant, count in ((tenant_a, 3), (tenant_b, 1)):
            activate_tenant_session(setup, tenant)
            for index in range(1, count + 1):
                mission = Mission(id=uuid.uuid4(), tenant_id=tenant, objective=f"Mission {index}")
                setup.add(mission)
                setup.flush()
                signal = canonical_signal(index, evaluated_at=evaluated + timedelta(hours=index)).model_copy(
                    update={
                        "episode_reference": canonical_signal(index).episode_reference.model_copy(
                            update={"mission_id": str(mission.id)}
                        )
                    }
                )
                setup.add(
                    EvidenceRecord(
                        tenant_id=tenant,
                        mission_id=mission.id,
                        evidence_type="execution_trace",
                        evidence_source="decision_episode_materialization",
                        summary="canonical durable learning signal",
                        structured_payload=signal.model_dump(mode="json"),
                        provenance_metadata={
                            "action_name": "analysis.materialize_decision_learning_signal",
                            "evidence_role": "decision_learning_signal",
                        },
                        materialization_reference={"action": "analysis.materialize_decision_learning_signal"},
                        # Persistence order intentionally opposes evaluation order.
                        created_at=evaluated + timedelta(hours=20 - index),
                    )
                )
        setup.commit()

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

    assert len(first.output["records_inspected"]) == 3
    earliest = datetime.fromisoformat(
        first.output["experience"]["pattern_candidates"][0]["earliest_evaluated_at"].replace("Z", "+00:00")
    )
    assert earliest == evaluated + timedelta(hours=1)
    assert first.output["qualifications"][0]["qualification"]["status"] == "qualified"
    assert first.output["qualifications"][0]["ledger_write"]["status"] == "recorded"
    assert replay.output["qualifications"][0]["ledger_write"]["status"] == "already_recorded"

    with factory() as verify:
        activate_tenant_session(verify, tenant_a)
        assert (
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant_a)
            )
            == 1
        )
        assert (
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeArtifactRecord)
                .where(KnowledgeArtifactRecord.tenant_id == tenant_a)
            )
            == 1
        )
        activate_tenant_session(verify, tenant_b)
        assert (
            verify.scalar(
                select(func.count())
                .select_from(KnowledgeQualificationRecord)
                .where(KnowledgeQualificationRecord.tenant_id == tenant_b)
            )
            == 0
        )
