"""PostgreSQL proof for the need-assessment → reviewed-composition spine edge."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.api.routes import mission as mission_module
from backend.api.routes import mission_composition as composition_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.db.tenant_session import activate_tenant_session
from backend.domain.audit_event import AuditEvent
from backend.domain.business_understanding import BusinessMeasurement, BusinessNeedAssessment, BusinessNeedRevision
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.business_understanding.service import BusinessUnderstandingService
from backend.services.mission_composition.proposal_store import get_proposal
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration


def _build_app(*, tenant_id: uuid.UUID, session, queue_adapter) -> FastAPI:
    """Use the production route owners with a tenant-admin principal fixture."""

    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="assessment-spine-operator",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(composition_module.router, prefix="/v1")
    app.include_router(mission_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: session
    app.dependency_overrides[get_queue_adapter] = lambda: queue_adapter
    return app


def _persist_assessed_need(*, session, tenant_id: str) -> tuple[str, BusinessNeedAssessment, BusinessMeasurement]:
    """Persist a bounded tenant need using the same source contracts as the service."""

    need_id = "need-conversion-gap"
    subject = {"schema_version": 1, "object_type": "opportunity", "object_id": "opp-42"}
    evaluated_at = datetime(2026, 10, 25, 4, 0, tzinfo=UTC)
    revision = BusinessNeedRevision(
        tenant_id=tenant_id,
        need_id=need_id,
        revision=1,
        origin="observed",
        status="recognized",
        subject_references=[subject],
        objective_reference={"objective_key": "increase_conversion"},
        condition_summary="Conversion is below the approved target.",
        uncertainty=[{"kind": "causal", "summary": "The cause remains unresolved."}],
        observation_references=[],
        related_need_references=[],
        candidate_responses=[],
        proposal_references=[],
        mission_references=[],
        resolution_observation_references=[],
        producer="test.business_understanding",
    )
    session.add(revision)
    session.flush()
    assessment = BusinessNeedAssessment(
        tenant_id=tenant_id,
        need_id=need_id,
        need_revision=1,
        need_revision_id=revision.id,
        assessment_fingerprint="sha256:" + "a" * 64,
        producer="test.business_need_reasoning",
        assessment_json={
            "tenant_id": tenant_id,
            "need_id": need_id,
            "need_revision": 1,
            "condition_summary": revision.condition_summary,
            "candidate_responses": [
                {
                    "response_key": "inspect_funnel",
                    "summary": "Inspect funnel conversion before changing spend.",
                    "evidence_status": "supported",
                    "knowledge_support_status": "not_provided",
                    "dependencies": [],
                    "assumptions": [],
                    "tradeoffs": [],
                }
            ],
            "causes": [],
            "information_gaps": ["stage-level conversion measurements"],
            "supporting_observation_ids": [],
            "contradictory_observation_ids": [],
            "knowledge_epistemic_limits": [],
            "evaluated_at": evaluated_at.isoformat(),
        },
    )
    session.add(assessment)
    session.flush()
    baseline = BusinessMeasurement(
        tenant_id=tenant_id,
        subject_references=[subject],
        objective_key="increase_conversion",
        metric="conversion",
        values=[],
        value=0.5,
        unit="ratio",
        period_start=datetime(2026, 9, 1, tzinfo=UTC),
        period_end=datetime(2026, 9, 30, tzinfo=UTC),
        observed_at=datetime(2026, 9, 30, 12, tzinfo=UTC),
        source_kind="customer_attested",
        source_reference={"source_id": "test-fixture:baseline-conversion"},
        source_version="baseline-1",
        source_content_fingerprint="sha256:" + "b" * 64,
        limitations=[{"code": "customer_attested"}],
        confidence=None,
    )
    session.add(baseline)
    session.flush()
    return need_id, assessment, baseline


def test_tenant_assessment_composes_to_existing_knowledge_decision_with_immutable_snapshots(pg_engine) -> None:
    """Only a tenant-owned assessment can make the contextual review executable."""

    tenant_id = str(uuid.uuid4())
    need_id = "need-conversion-gap"
    subject = {"schema_version": 1, "object_type": "opportunity", "object_id": "opp-42"}
    evaluated_at = datetime(2026, 10, 25, 4, 0, tzinfo=UTC)
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)

    with factory() as session:
        session.add(
            Tenant(id=uuid.UUID(tenant_id), name="Assessment spine", slug=f"spine-{tenant_id[:8]}", plan="free")
        )
        session.commit()
        activate_tenant_session(session, tenant_id)
        persist_test_operating_charter(session, tenant_id=tenant_id)

        revision = BusinessNeedRevision(
            tenant_id=tenant_id,
            need_id=need_id,
            revision=1,
            origin="observed",
            status="recognized",
            subject_references=[subject],
            objective_reference={"objective_key": "increase_conversion"},
            condition_summary="Conversion is below the approved target.",
            uncertainty=[{"kind": "causal", "summary": "The cause remains unresolved."}],
            observation_references=[],
            related_need_references=[],
            candidate_responses=[],
            proposal_references=[],
            mission_references=[],
            resolution_observation_references=[],
            producer="test.business_understanding",
        )
        session.add(revision)
        session.flush()
        assessment = BusinessNeedAssessment(
            tenant_id=tenant_id,
            need_id=need_id,
            need_revision=1,
            need_revision_id=revision.id,
            assessment_fingerprint="sha256:" + "a" * 64,
            producer="test.business_need_reasoning",
            assessment_json={
                "tenant_id": tenant_id,
                "need_id": need_id,
                "need_revision": 1,
                "condition_summary": revision.condition_summary,
                "candidate_responses": [
                    {
                        "response_key": "inspect_funnel",
                        "summary": "Inspect funnel conversion before changing spend.",
                        "evidence_status": "supported",
                        "knowledge_support_status": "not_provided",
                        "dependencies": [],
                        "assumptions": [],
                        "tradeoffs": [],
                    }
                ],
                "causes": [],
                "information_gaps": ["stage-level conversion measurements"],
                "supporting_observation_ids": [],
                "contradictory_observation_ids": [],
                "knowledge_epistemic_limits": [],
                "evaluated_at": evaluated_at.isoformat(),
            },
        )
        session.add(assessment)
        session.commit()

        record = MissionCompositionService(db=session).compose(
            tenant_id=tenant_id,
            instruction="Review the referenced business need assessment and recommend the next action.",
            business_need_reference={"need_id": need_id, "revision": 1},
            business_need_assessment_reference={"assessment_id": str(assessment.id)},
        )
        persisted = get_proposal(tenant_id=tenant_id, proposal_id=record.proposal_id, db=session)
        confirmation = MissionCompositionService(db=session).confirm(
            tenant_id=tenant_id,
            proposal_id=record.proposal_id,
            idempotency_key="assessment-spine-confirm-v1",
        )

    assert record.intent.interpretation_ready
    assert record.intent.requested_outcomes == ["review_business_need"]
    assert record.semantic_snapshot is not None
    assert record.reviewed_composition_snapshot is not None
    assert record.semantic_snapshot.business_need_reference is not None
    assert record.semantic_snapshot.business_need_assessment_reference is not None
    assert record.semantic_snapshot.business_need_assessment_reference["assessment_id"] == str(assessment.id)
    assert record.semantic_snapshot.business_need_assessment_reference["grants_execution_authority"] is False
    assert record.reviewed_composition_snapshot.selected_job_keys == ("business.review_need_with_knowledge",)
    assert [step.action_name for step in record.planned_steps] == ["knowledge.inform_decision"]
    assert record.ready_to_start
    assert persisted is not None
    assert persisted.semantic_snapshot.model_dump(mode="json") == record.semantic_snapshot.model_dump(mode="json")
    assert persisted.reviewed_composition_snapshot.model_dump(
        mode="json"
    ) == record.reviewed_composition_snapshot.model_dump(mode="json")
    assert confirmation["allowed_actions"] == ["knowledge.inform_decision"]
    assert confirmation["runtime_queued"] is False
    assert [node["metadata"]["action"] for node in confirmation["task_graph"]["nodes"]] == ["knowledge.inform_decision"]


def test_assessed_need_reaches_existing_runtime_and_persists_decision_evidence(
    pg_engine,
    queue_adapter,
    redis_client,
) -> None:
    """Exercise the production spine from a persisted assessment through dispatch.

    The composed action is the existing internal knowledge decision support action;
    this verifies that the assessment context does not itself grant authority or
    bypass the graph materialization, runtime admission, queue, lease, or worker
    boundaries.
    """

    tenant_uuid = uuid.uuid4()
    tenant_id = str(tenant_uuid)
    worker_id = "assessment-spine-worker"
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup = factory()
    try:
        setup.add(Tenant(id=tenant_uuid, name="Assessment runtime", slug=f"assessment-{tenant_id[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_id)
        persist_test_operating_charter(setup, tenant_id=tenant_id)
        need_id, assessment, baseline = _persist_assessed_need(session=setup, tenant_id=tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_uuid, session=setup, queue_adapter=queue_adapter)
        # The production authorization dependency is exercised extensively by
        # route tests.  This integration fixture has no persisted membership
        # record, so retain the existing route-test pattern while proving every
        # downstream durable runtime authority with PostgreSQL and Redis.
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed = client.post(
                "/v1/missions/compose",
                json={
                    "instruction": "Review the referenced business need assessment and recommend the next action.",
                    "business_need_id": need_id,
                    "business_need_revision": 1,
                    "business_need_assessment_id": str(assessment.id),
                    "business_need_response_key": "inspect_funnel",
                    "business_need_baseline_measurement_id": str(baseline.id),
                },
            )
            assert composed.status_code == 200, composed.text
            composition = composed.json()
            assert composition["allowed_actions"] == ["knowledge.inform_decision"]
            selected = composition["composition"]["semantic_snapshot"]["business_need_assessment_reference"]
            assert selected["selected_candidate_response_key"] == "inspect_funnel"
            assert selected["response_advancement"]["baseline_measurement"]["measurement_id"] == str(baseline.id)
            assert selected["grants_execution_authority"] is False

            confirmed = client.post(
                f"/v1/missions/proposals/{composition['proposal_id']}/confirm",
                json={"composition": composition["composition"], "idempotency_key": "assessment-runtime-spine-v1"},
            )
            assert confirmed.status_code == 200, confirmed.text
            mission_id = uuid.UUID(confirmed.json()["mission_id"])

            launched = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched.status_code == 200, launched.text
            launch = launched.json()
            assert launch["compile_status"] == "ready"
            assert launch["graph_materialized"] is True
            assert launch["runtime_admitted"] is True
            assert len(launch["queued_task_ids"]) == 1
            assert launch["blockers"] == []
        setup.commit()

        task_id = uuid.UUID(launch["queued_task_ids"][0])
        runtime = WorkerRuntimeService(setup, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        assert claimed.id == task_id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup.commit()
    finally:
        setup.close()

    TaskDispatcher(
        session_factory=factory,
        vector_session_factory=factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    ).execute(task_id=task_id, lease_id=lease_id)

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_id)
        task = verify.get(ExecutionTask, task_id)
        lease = verify.get(WorkerLease, lease_id)
        evidence = verify.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.execution_task_id == task_id,
            )
        ).all()
        audit_events = verify.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.mission_id == mission_id,
            )
        ).all()
        assert task is not None
        assert task.status == ExecutionTaskState.COMPLETED.value
        assert task.metadata_json["handler_result"]["action"] == "knowledge.inform_decision"
        assert task.metadata_json["handler_result"]["side_effect_class"] == "internal_read"
        assert lease is not None
        assert lease.status == WorkerLeaseState.RELEASED.value
        assert evidence
        assert any(item.evidence_source == "knowledge_decision_support" for item in evidence)
        queue_fact = next(
            RuntimeEvidenceLedger.read_envelope(item)
            for item in audit_events
            if (envelope := RuntimeEvidenceLedger.read_envelope(item)) is not None
            and envelope.event_type == "runtime_evidence.queue_admission_recorded"
        )
        assert queue_fact is not None
        assert "response_advancement" in queue_fact.facts["semantic_lineage"]
        assert redis_client.hlen(f"ajenda:queue:{tenant_id}:v2:processing-payloads") == 0

        subject = {"schema_version": 1, "object_type": "opportunity", "object_id": "opp-42"}
        goal = Goal(
            goal_id="goal-increase-conversion",
            objective_key="increase_conversion",
            name="Increase conversion",
            subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id="opp-42")],
        )

        def ingest_later(*, version: str, observed_at: datetime) -> BusinessMeasurement:
            measurement, _ = BusinessUnderstandingService(verify).ingest_measurement(
                tenant_id=tenant_id,
                goal=goal,
                kpis=[
                    Kpi(
                        kpi_id="conversion",
                        goal_id=goal.goal_id,
                        name="Conversion",
                        metric="conversion",
                        direction="increase",
                        current_value=0.6,
                        target_value=0.75,
                        previous_value=0.5,
                        unit="ratio",
                    )
                ],
                subject_references=[subject],
                source_kind="customer_attested",
                source_reference={"source_id": f"test-fixture:later-conversion:{version}"},
                source_version=version,
                measurement_period_start=datetime(2026, 10, 1, tzinfo=UTC),
                measurement_period_end=datetime(2026, 10, 31, tzinfo=UTC),
                observed_at=observed_at,
                successor_mission_id=mission_id,
                limitations=[{"code": "customer_attested"}],
                confidence=None,
                producer="test.measurement_intake",
            )
            return measurement

        later_one = ingest_later(version="later-1", observed_at=datetime(2026, 11, 1, tzinfo=UTC))
        later_two = ingest_later(version="later-2", observed_at=datetime(2026, 12, 1, tzinfo=UTC))
        verify.commit()
        assert later_one.id != later_two.id
        assert later_one.intended_measurement_reference is not None
        assert later_two.intended_measurement_reference == later_one.intended_measurement_reference
        reference = later_one.intended_measurement_reference
        assert reference["successor_mission_id"] == str(mission_id)
        assert reference["strategy_lineage"]["need_id"] == need_id
        assert reference["measurement_contract"]["baseline_measurement_id"] == str(baseline.id)
        assert reference["measurement_contract"]["metric"] == "conversion"
        assert reference["grants_execution_authority"] is False
        statuses = verify.scalars(
            select(BusinessNeedRevision.status).where(BusinessNeedRevision.tenant_id == tenant_id)
        ).all()
        assert "impact_monitored" not in statuses
    finally:
        verify.close()
