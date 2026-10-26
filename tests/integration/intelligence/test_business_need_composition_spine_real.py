"""PostgreSQL proof for the need-assessment → reviewed-composition spine edge."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
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
from backend.domain.business_understanding import (
    BusinessMeasurement,
    BusinessMeasurementPairing,
    BusinessNeedAssessment,
    BusinessNeedRevision,
)
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.repositories.durable_learning_signal_repository import DurableLearningSignalRepository
from backend.repositories.evidence_repository import EvidenceRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
)
from backend.services.decision_episode_materialization import (
    DecisionEpisodeMaterializationRequest,
    DecisionEpisodeMaterializationService,
)
from backend.services.durable_experience_consolidation import DurableExperienceConsolidationService
from backend.services.mission_composition.proposal_store import get_proposal
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.ontology.commercial_state import Goal, Kpi
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.intelligence.canonical_decision_runtime import execute_canonical_action
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
        values=[
            {
                "kpi_id": "conversion",
                "goal_id": "goal-increase-conversion",
                "name": "Conversion",
                "metric": "conversion",
                "direction": "increase",
                "current_value": 0.5,
                "target_value": 0.75,
                "unit": "ratio",
            }
        ],
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

        current = BusinessUnderstandingRepository(verify).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need_id
        )
        assert current is not None
        pairing = BusinessUnderstandingService(verify).accept_measurement_pairing(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=current.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later_one.id,
            producer="test.accepted_measurement_pairing",
        )
        verify.commit()
    finally:
        verify.close()

    outcome = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": {
                "goal_id": "goal-increase-conversion",
                "objective_key": "increase_conversion",
                "name": "Increase conversion",
                "subject_refs": [subject],
            },
            "subject_refs": [subject],
            "baseline_kpis": baseline.values,
            "observed_kpis": later_one.values,
            "source_observed_at": later_one.observed_at.isoformat(),
            "accepted_measurement_pairing_id": str(pairing.id),
            "outcome_evaluation_id": "assessment-spine-conversion-v1",
            "evidence_ids": [str(evidence[0].id)],
        },
        worker_label="assessment-spine-outcome",
    )
    # A tenant-owned declarative row may copy the valid outcome payload and
    # advertise the expected action name. It must not acquire runtime authority.
    with factory() as forged_session:
        activate_tenant_session(forged_session, tenant_id)
        forged = EvidenceRecord(
            tenant_id=tenant_id,
            mission_id=mission_id,
            evidence_type="artifact",
            evidence_source="customer_declared",
            summary="Alleged canonical outcome without runtime lineage",
            structured_payload=outcome.structured_payload,
            provenance_metadata={"action_name": "analysis.evaluate_outcome"},
            trust_signal={},
            collection_status="collected",
        )
        forged_session.add(forged)
        forged_session.commit()
    with factory() as forged_attempt:
        activate_tenant_session(forged_attempt, tenant_id)
        current = BusinessUnderstandingRepository(forged_attempt).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need_id
        )
        assert current is not None
        with pytest.raises(BusinessUnderstandingValidationError, match="authorized runtime provenance"):
            BusinessUnderstandingService(forged_attempt).record_canonical_measurement_impact(
                tenant_id=tenant_id,
                need_id=need_id,
                expected_revision=current.revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later_one.id,
                outcome_evidence_id=forged.id,
                accepted_measurement_pairing_id=pairing.id,
                producer="test.forged_outcome_denied",
            )
        forged_attempt.rollback()
    impact = factory()
    try:
        activate_tenant_session(impact, tenant_id)
        current = BusinessUnderstandingRepository(impact).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need_id
        )
        assert current is not None
        impact_revision, evaluation = BusinessUnderstandingService(impact).record_canonical_measurement_impact(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=current.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later_one.id,
            outcome_evidence_id=outcome.id,
            accepted_measurement_pairing_id=pairing.id,
            producer="test.accepted_measurement_impact",
        )
        impact.commit()
    finally:
        impact.close()

    readback = factory()
    try:
        activate_tenant_session(readback, tenant_id)
        persisted_pairing = readback.get(BusinessMeasurementPairing, pairing.id)
        persisted_impact = readback.get(BusinessNeedRevision, impact_revision.id)
        assert persisted_pairing is not None
        assert persisted_pairing.status == "evaluated"
        assert persisted_pairing.outcome_evidence_id == outcome.id
        assert persisted_pairing.outcome_evaluation_id == evaluation.outcome_evaluation_id
        assert persisted_pairing.impact_revision_id == impact_revision.id
        assert persisted_impact is not None
        assert persisted_impact.status == "impact_monitored"
        assert persisted_impact.impact_assessment is not None
        assert persisted_impact.impact_assessment["accepted_measurement_pairing_id"] == str(pairing.id), (
            persisted_impact.impact_assessment
        )
        assert persisted_impact.impact_assessment["outcome_evidence_id"] == str(outcome.id)
        assert persisted_pairing.successor_contract_id == later_one.intended_measurement_reference["contract_id"]
        episode = DecisionEpisodeMaterializationService(
            session=readback,
            evidence=EvidenceRepository(readback),
            tasks=ExecutionTaskRepository(readback),
        ).materialize(
            tenant_id=tenant_id,
            request=DecisionEpisodeMaterializationRequest(impact_revision_id=impact_revision.id),
        )
        replay = DecisionEpisodeMaterializationService(
            session=readback,
            evidence=EvidenceRepository(readback),
            tasks=ExecutionTaskRepository(readback),
        ).materialize(
            tenant_id=tenant_id,
            request=DecisionEpisodeMaterializationRequest(impact_revision_id=impact_revision.id),
        )
        assert episode.episode_reference.episode_kind == "business_impact"
        assert episode.episode_reference.episode_id == replay.episode_reference.episode_id
        assert episode.feedback is None
        observation = episode.business_impact_observation
        assert observation is not None
        assert observation.execution_status == "unknown"
        assert observation.selected_candidate_response_key == "inspect_funnel"
        assert observation.baseline_source_kind == "customer_attested"
        assert observation.observed_source_kind == "customer_attested"
        assert observation.outcome_timing_verification_basis.value == outcome.structured_payload["observation_timing"]["verification_basis"]
        provenance = episode.episode_reference.business_impact_provenance
        assert provenance is not None
        assert provenance["accepted_measurement_pairing_id"] == str(pairing.id)
        assert provenance["impact_revision_id"] == str(impact_revision.id)
        assert provenance["outcome_evidence_id"] == str(outcome.id)
        assert provenance["frozen_successor_contract"] == later_one.intended_measurement_reference
        strategy = provenance["frozen_successor_contract"]["strategy_lineage"]
        assessment_row = readback.get(BusinessNeedAssessment, uuid.UUID(strategy["assessment_id"]))
        assert assessment_row is not None
        original_fingerprint = assessment_row.assessment_fingerprint
        assessment_row.assessment_fingerprint = "sha256:" + "0" * 64
        readback.flush()
        with pytest.raises(ValueError, match="originating assessment authority"):
            DecisionEpisodeMaterializationService(
                session=readback,
                evidence=EvidenceRepository(readback),
                tasks=ExecutionTaskRepository(readback),
            ).materialize(
                tenant_id=tenant_id,
                request=DecisionEpisodeMaterializationRequest(impact_revision_id=impact_revision.id),
            )
        readback.rollback()
        assert assessment_row.assessment_fingerprint == original_fingerprint
    finally:
        readback.close()

    # This is the canonical write boundary: the analysis action derives the
    # signal from Layer 2 records and the worker persists it through
    # EvidenceBridge.  No recommendation or execution artifact is supplied.
    business_impact_signal = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.materialize_decision_learning_signal",
        action_input={"impact_revision_id": str(impact_revision.id)},
        worker_label="assessment-spine-business-impact",
    )
    assert business_impact_signal.logical_identity == episode.episode_reference.episode_id
    assert business_impact_signal.structured_payload["episode_reference"]["episode_kind"] == "business_impact"
    assert business_impact_signal.structured_payload["episode_reference"]["business_impact_provenance"] == provenance
    learning_readback = factory()
    try:
        activate_tenant_session(learning_readback, tenant_id)
        history = DurableExperienceConsolidationService(
            history=DurableLearningSignalRepository(learning_readback)
        ).consolidate(learning_readback, tenant_id=tenant_id)
        assert episode.episode_reference.episode_id in history.authoritative_episode_ids
        assert episode.episode_reference.episode_id in history.observational_episode_ids
        assert observation.signal_id not in history.valid_learning_signal_ids
        assert business_impact_signal.provenance_metadata["evidence_role"] == "business_impact_observation"
    finally:
        learning_readback.close()

    def retry_from_independent_session() -> uuid.UUID:
        session = factory()
        try:
            activate_tenant_session(session, tenant_id)
            revision, _ = BusinessUnderstandingService(session).record_canonical_measurement_impact(
                tenant_id=tenant_id,
                need_id=need_id,
                # An evaluated pairing is idempotently addressable by the
                # frozen revision it accepted, even after the impact append.
                expected_revision=pairing.need_revision,
                baseline_measurement_id=baseline.id,
                observed_measurement_id=later_one.id,
                outcome_evidence_id=outcome.id,
                accepted_measurement_pairing_id=pairing.id,
                producer="test.concurrent_retry",
            )
            session.commit()
            return revision.id
        finally:
            session.close()

    # Each worker owns an independent PostgreSQL session and transaction.  The
    # repository's SELECT .. FOR UPDATE serializes the pairing read; both see
    # the same finalized impact revision rather than appending another one.
    with ThreadPoolExecutor(max_workers=2) as executor:
        retry_ids = list(executor.map(lambda _: retry_from_independent_session(), range(2)))
    assert retry_ids == [impact_revision.id, impact_revision.id]

    accepted = factory()
    try:
        activate_tenant_session(accepted, tenant_id)
        latest = BusinessUnderstandingRepository(accepted).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need_id
        )
        assert latest is not None
        rollback_pairing = BusinessUnderstandingService(accepted).accept_measurement_pairing(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=latest.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later_two.id,
            producer="test.rollback_pairing",
        )
        accepted.commit()
    finally:
        accepted.close()

    rollback_outcome = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": {
                "goal_id": "goal-increase-conversion",
                "objective_key": "increase_conversion",
                "name": "Increase conversion",
                "subject_refs": [subject],
            },
            "subject_refs": [subject],
            "baseline_kpis": baseline.values,
            "observed_kpis": later_two.values,
            "source_observed_at": later_two.observed_at.isoformat(),
            "accepted_measurement_pairing_id": str(rollback_pairing.id),
            "outcome_evaluation_id": "assessment-spine-conversion-rollback-v1",
            "evidence_ids": [str(evidence[0].id)],
        },
        worker_label="assessment-spine-rollback-outcome",
    )
    interrupted = factory()
    try:
        activate_tenant_session(interrupted, tenant_id)
        latest = BusinessUnderstandingRepository(interrupted).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need_id
        )
        assert latest is not None
        BusinessUnderstandingService(interrupted).record_canonical_measurement_impact(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=latest.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later_two.id,
            outcome_evidence_id=rollback_outcome.id,
            accepted_measurement_pairing_id=rollback_pairing.id,
            producer="test.interrupted_outer_transaction",
        )
        # Simulate an outer transaction failure after both the append and the
        # pairing update have flushed; no service-level commit is allowed.
        interrupted.rollback()
    finally:
        interrupted.close()

    rollback_readback = factory()
    try:
        activate_tenant_session(rollback_readback, tenant_id)
        persisted_rollback_pairing = rollback_readback.get(BusinessMeasurementPairing, rollback_pairing.id)
        assert persisted_rollback_pairing is not None
        assert persisted_rollback_pairing.status == "accepted"
        assert persisted_rollback_pairing.outcome_evidence_id is None
        assert persisted_rollback_pairing.outcome_evaluation_id is None
        assert persisted_rollback_pairing.impact_revision_id is None
        revisions = rollback_readback.scalars(
            select(BusinessNeedRevision).where(
                BusinessNeedRevision.tenant_id == tenant_id, BusinessNeedRevision.need_id == need_id
            )
        ).all()
        assert all(
            row.impact_assessment is None
            or row.impact_assessment.get("outcome_evidence_id") != str(rollback_outcome.id)
            for row in revisions
        )
    finally:
        rollback_readback.close()
