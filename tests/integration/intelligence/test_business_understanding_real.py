"""PostgreSQL proof for business-understanding persistence and isolation."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command as alembic_command
from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_profile import BusinessProfile
from backend.domain.business_understanding import BusinessMeasurement, BusinessNeedRevision, BusinessObservation
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.business_understanding_repository import (
    BusinessNeedRevisionConflict,
    BusinessUnderstandingRepository,
)
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.business_understanding.reasoning import (
    BusinessNeedReasoningService,
    NeedAssessmentRequest,
    NeedCandidateResponse,
    NeedCauseHypothesis,
)
from backend.services.business_understanding.service import (
    BusinessUnderstandingService,
    BusinessUnderstandingValidationError,
    SourceReference,
)
from backend.services.knowledge.knowledge_decision_support import (
    KnowledgeDecisionInfluence,
    KnowledgeDecisionSupportResult,
    KnowledgeInfluenceDirection,
)
from backend.services.ontology.commercial_state import Goal, Kpi, KpiDirection
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType
from tests.integration.intelligence.canonical_decision_runtime import (
    EXECUTION_ACTION,
    MATERIALIZATION_ACTION,
    execute_canonical_action,
    seed_execution_authority,
)
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration


def _tenant() -> str:
    return f"tenant-business-understanding-{uuid.uuid4()}"


def _record_acquisition_observation(
    session: Session, *, tenant_id: str, source_id: str, observed_at: datetime | None = None
) -> BusinessObservation:
    return BusinessUnderstandingService(session).record_observation(
        tenant_id=tenant_id,
        source=SourceReference(
            source_kind="external_provider",
            reference={"source_id": source_id, "provider": "fixture-metrics"},
        ),
        observation_summary="Customer acquisition is below the verified target for the observed period.",
        subject_references=[{"kind": "organization", "id": "self"}],
        observed_at=observed_at or datetime.now(UTC),
        confidence=0.9,
        limitations=[{"code": "CAUSE_UNVERIFIED"}],
        producer="integration-test",
    )


def _initial_need(
    service: BusinessUnderstandingService, *, tenant_id: str, observation_id: uuid.UUID
) -> BusinessNeedRevision:
    return service.append_need_revision(
        tenant_id=tenant_id,
        need_id=None,
        expected_revision=0,
        origin="observed",
        status="recognized",
        subject_references=[{"kind": "organization", "id": "self"}],
        objective_reference={"objective_key": "customer_acquisition"},
        condition_summary="Customer acquisition may require attention; lead quality, channel fit, messaging, pricing, and onboarding remain hypotheses.",
        uncertainty=[{"code": "CAUSE_UNVERIFIED"}],
        priority={"level": "high", "basis": "below_target"},
        confidence=0.75,
        observation_ids=[observation_id],
        related_need_references=[],
        candidate_responses=[
            {
                "response_key": "investigate_acquisition_causes",
                "capability_status": "available",
                "grants_execution_authority": False,
            },
            {
                "response_key": "evaluate_pricing",
                "capability_status": "unknown",
                "grants_execution_authority": False,
            },
        ],
        proposal_references=[],
        mission_references=[],
        impact_assessment=None,
        resolution_observation_ids=[],
        producer="integration-test",
    )


def _goal_and_kpis(*, current: float, previous: float | None = None) -> tuple[Goal, list[Kpi]]:
    goal = Goal(
        goal_id="customer-acquisition",
        objective_key="customer_acquisition",
        name="Acquire qualified customers",
        subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="ajenda")],
    )
    return goal, [
        Kpi(
            kpi_id="qualified-customers",
            goal_id=goal.goal_id,
            name="Qualified customers",
            metric="qualified_customers",
            direction=KpiDirection.INCREASE,
            current_value=current,
            target_value=10,
            previous_value=previous,
            unit="customers",
        )
    ]


def _ingest_customer_measurement(
    session: Session,
    *,
    tenant_id: str,
    current: float,
    source_version: str,
    period_start: datetime,
    period_end: datetime,
    previous: float | None = None,
) -> tuple[BusinessMeasurement, BusinessNeedRevision | None]:
    goal, kpis = _goal_and_kpis(current=current, previous=previous)
    return BusinessUnderstandingService(session).ingest_measurement(
        tenant_id=tenant_id,
        goal=goal,
        kpis=kpis,
        subject_references=[item.model_dump(mode="json") for item in goal.subject_refs],
        source_kind="customer_attested",
        source_reference={"source_id": "monthly-operating-statement"},
        source_version=source_version,
        measurement_period_start=period_start,
        measurement_period_end=period_end,
        observed_at=period_end + timedelta(hours=12),
        limitations=[{"code": "customer_attested_not_independently_verified"}],
        confidence=None,
        producer="integration-test",
    )


def test_measurement_replay_change_and_recovery_preserve_one_continuing_need(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    january_start = datetime(2026, 1, 1, tzinfo=UTC)
    january_end = datetime(2026, 1, 31, tzinfo=UTC)
    first_measurement, first_need = _ingest_customer_measurement(
        pg_session,
        tenant_id=tenant_id,
        current=2,
        previous=3,
        source_version="jan-v1",
        period_start=january_start,
        period_end=january_end,
    )
    replay_measurement, replay_need = _ingest_customer_measurement(
        pg_session,
        tenant_id=tenant_id,
        current=2,
        previous=3,
        source_version="jan-v1",
        period_start=january_start,
        period_end=january_end,
    )
    assert first_need is not None and replay_need is not None
    assert replay_measurement.id == first_measurement.id
    assert replay_need.id == first_need.id

    february_start = datetime(2026, 2, 1, tzinfo=UTC)
    february_end = datetime(2026, 2, 28, tzinfo=UTC)
    _, recovered = _ingest_customer_measurement(
        pg_session,
        tenant_id=tenant_id,
        current=10,
        previous=2,
        source_version="feb-v1",
        period_start=february_start,
        period_end=february_end,
    )
    assert recovered is not None
    assert recovered.need_id == first_need.need_id
    assert recovered.revision == 2
    assert recovered.status == "monitoring"
    assert len(recovered.observation_references) == 2

    march_start = datetime(2026, 3, 1, tzinfo=UTC)
    march_end = datetime(2026, 3, 31, tzinfo=UTC)
    _, deteriorated = _ingest_customer_measurement(
        pg_session,
        tenant_id=tenant_id,
        current=1,
        previous=10,
        source_version="mar-v1",
        period_start=march_start,
        period_end=march_end,
    )
    assert deteriorated is not None
    assert deteriorated.need_id == first_need.need_id
    assert deteriorated.revision == 3
    assert deteriorated.status == "monitoring"
    assert len(deteriorated.observation_references) == 3


def test_non_sales_operating_measurement_uses_same_continuing_need_contract(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    subject = BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="manufacturing-line")
    goal = Goal(
        goal_id="reduce-defects",
        objective_key="manufacturing_quality",
        name="Reduce manufacturing defects",
        subject_refs=[subject],
    )

    def ingest(*, current: float, previous: float, month: int) -> BusinessNeedRevision | None:
        _, need = BusinessUnderstandingService(pg_session).ingest_measurement(
            tenant_id=tenant_id,
            goal=goal,
            kpis=[
                Kpi(
                    kpi_id="defect-rate",
                    goal_id=goal.goal_id,
                    name="Defect rate",
                    metric="defect_rate",
                    direction=KpiDirection.DECREASE,
                    current_value=current,
                    previous_value=previous,
                    target_value=5,
                    unit="percent",
                )
            ],
            subject_references=[subject.model_dump(mode="json")],
            source_kind="customer_attested",
            source_reference={"source_id": "quality-control-report"},
            source_version=f"2026-{month:02d}",
            measurement_period_start=datetime(2026, month, 1, tzinfo=UTC),
            measurement_period_end=datetime(2026, month, 20, tzinfo=UTC),
            observed_at=datetime(2026, month, 21, tzinfo=UTC),
            limitations=[{"code": "customer_attested_not_independently_verified"}],
            confidence=None,
            producer="integration-test",
        )
        return need

    initial = ingest(current=12, previous=10, month=6)
    improved = ingest(current=4, previous=12, month=7)
    assert initial is not None and improved is not None
    assert improved.need_id == initial.need_id
    assert improved.revision == 2
    assert improved.status == "monitoring"
    assert improved.objective_reference == initial.objective_reference


def test_concurrent_identical_measurement_ingestion_creates_one_history(pg_engine) -> None:
    tenant_id = _tenant()
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    period_start = datetime(2026, 4, 1, tzinfo=UTC)
    period_end = datetime(2026, 4, 30, tzinfo=UTC)

    def ingest() -> tuple[uuid.UUID, str]:
        with factory() as session:
            activate_tenant_session(session, tenant_id)
            measurement, need = _ingest_customer_measurement(
                session,
                tenant_id=tenant_id,
                current=2,
                previous=3,
                source_version="apr-v1",
                period_start=period_start,
                period_end=period_end,
            )
            assert need is not None
            session.commit()
            return measurement.id, need.need_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: ingest(), range(2)))
    assert len({item[0] for item in results}) == 1
    assert len({item[1] for item in results}) == 1
    with factory() as verify:
        activate_tenant_session(verify, tenant_id)
        assert verify.scalar(select(func.count()).select_from(BusinessMeasurement)) == 1
        assert verify.scalar(select(func.count()).select_from(BusinessObservation)) == 1
        assert verify.scalar(select(func.count()).select_from(BusinessNeedRevision)) == 1


def test_customer_attested_measurement_impact_flows_to_canonical_learning_candidate(
    pg_engine, queue_adapter, redis_client
) -> None:
    """One outcome identity links durable impact and canonical feedback.

    Customer-attested measurements can update understanding, but the learning
    signal retains their bounded evidence and is not promoted here.
    """

    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        setup.add(Tenant(id=uuid.UUID(tenant_id), name="Ajenda", slug=f"ajenda-{tenant_id[:8]}", plan="free"))
        setup.add(Mission(id=mission_id, tenant_id=tenant_id, objective="Improve customer acquisition"))
        activate_tenant_session(setup, tenant_id)
        persist_test_operating_charter(setup, tenant_id=tenant_id)
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant_id,
            record_type="account",
            record_id="ajenda",
            data={"name": "Ajenda", "measurement_scope": "customer_acquisition"},
        )
        baseline, need = _ingest_customer_measurement(
            setup,
            tenant_id=tenant_id,
            current=2,
            previous=3,
            source_version="2026-01",
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 31, tzinfo=UTC),
        )
        assert need is not None
        setup.commit()

    supporting = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "account", "record_id": "ajenda"},
        worker_label="business-impact-source",
    )
    recommendation = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="decision.recommend_next_action",
        action_input={
            "goal": "Improve customer acquisition",
            "goal_ref": {
                "goal_id": "customer-acquisition",
                "objective_key": "customer_acquisition",
                "name": "Acquire qualified customers",
                "subject_refs": [{"object_type": "organization", "object_id": "ajenda"}],
            },
            "subject_refs": [{"object_type": "organization", "object_id": "ajenda"}],
            "options": [
                {
                    "option_id": "improve-onboarding",
                    "label": "Improve onboarding",
                    "intervention_key": EXECUTION_ACTION,
                },
                {"option_id": "investigate", "label": "Investigate further", "intervention_key": "record.search"},
            ],
            "criteria": [{"criterion_id": "acquisition", "label": "Acquisition", "required": False}],
            "evidence": [
                {
                    "evidence_id": str(supporting.id),
                    "claim": "The account record establishes the business subject only.",
                    "status": "known",
                    "confidence": 0.8,
                    "supports_option_ids": ["improve-onboarding"],
                    "supports_criterion_ids": ["acquisition"],
                    "lineage": supporting.provenance_metadata["evidence_lineage"],
                }
            ],
        },
        worker_label="business-impact-decision",
    )
    execution = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action=EXECUTION_ACTION,
        action_input={
            "record_type": "activity",
            "record_id": "onboarding-improvement",
            "data": {"status": "completed", "subject_id": "ajenda"},
        },
        worker_label="business-impact-execution",
        runtime_authority_metadata=seed_execution_authority(factory=factory, tenant_id=tenant_id),
    )

    observed_at = datetime.fromisoformat(str(execution.structured_payload["executed_at"])) + timedelta(days=30)
    with factory() as measurement_session:
        activate_tenant_session(measurement_session, tenant_id)
        later, updated_need = _ingest_customer_measurement(
            measurement_session,
            tenant_id=tenant_id,
            current=4,
            previous=2,
            source_version="2026-02",
            period_start=observed_at - timedelta(days=29),
            period_end=observed_at - timedelta(hours=12),
        )
        assert updated_need is not None and updated_need.need_id == need.need_id
        measurement_session.commit()

    outcome = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": {
                "goal_id": "customer-acquisition",
                "objective_key": "customer_acquisition",
                "name": "Acquire qualified customers",
                "subject_refs": [{"object_type": "organization", "object_id": "ajenda"}],
            },
            "subject_refs": [{"object_type": "organization", "object_id": "ajenda"}],
            "baseline_kpis": baseline.values,
            "observed_kpis": later.values,
            "source_observed_at": later.observed_at.isoformat(),
            "evidence_ids": [str(execution.id)],
        },
        worker_label="business-impact-outcome",
    )
    with factory() as impact_session:
        activate_tenant_session(impact_session, tenant_id)
        current = BusinessUnderstandingRepository(impact_session).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need.need_id
        )
        assert current is not None
        impact_revision, evaluation = BusinessUnderstandingService(impact_session).record_canonical_measurement_impact(
            tenant_id=tenant_id,
            need_id=need.need_id,
            expected_revision=current.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later.id,
            outcome_evidence_id=outcome.id,
            producer="integration-test",
        )
        impact_session.commit()
    assert impact_revision.status == "impact_monitored"
    assert impact_revision.mission_references == [{"mission_id": str(mission_id)}]
    assert impact_revision.impact_assessment is not None
    assert impact_revision.impact_assessment["outcome_evidence_id"] == str(outcome.id)
    assert impact_revision.impact_assessment["causation"] == "unresolved"
    assert evaluation.attribution.value == "not_assessed"

    learning_record = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action=MATERIALIZATION_ACTION,
        action_input={
            "recommendation_evidence_id": str(recommendation.id),
            "outcome_evaluation_evidence_id": str(outcome.id),
            "execution_evidence_ids": [str(execution.id)],
        },
        worker_label="business-impact-learning",
    )
    signal = DecisionLearningSignal.model_validate(learning_record.structured_payload)
    assert signal.episode_reference is not None
    assert signal.episode_reference.outcome_evaluation_evidence_id == str(outcome.id)


def test_need_is_append_only_and_mission_work_does_not_resolve_it(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    service = BusinessUnderstandingService(pg_session)
    initial_observation = _record_acquisition_observation(
        pg_session, tenant_id=tenant_id, source_id="monthly-acquisition"
    )
    initial = _initial_need(service, tenant_id=tenant_id, observation_id=initial_observation.id)

    # A linked mission/outcome is evidence of work performed, not evidence that
    # the business condition improved.  A revision remains impact_monitored.
    work_outcome = _record_acquisition_observation(
        pg_session,
        tenant_id=tenant_id,
        source_id="campaign-delivered",
        observed_at=initial_observation.observed_at + timedelta(days=1),
    )
    monitoring = service.append_need_revision(
        tenant_id=tenant_id,
        need_id=initial.need_id,
        expected_revision=1,
        origin="observed",
        status="impact_monitored",
        subject_references=list(initial.subject_references),
        objective_reference=initial.objective_reference,
        condition_summary=initial.condition_summary,
        uncertainty=list(initial.uncertainty),
        priority=initial.priority,
        confidence=initial.confidence,
        observation_ids=[initial_observation.id, work_outcome.id],
        related_need_references=[],
        candidate_responses=list(initial.candidate_responses),
        proposal_references=[],
        mission_references=[],
        impact_assessment={"status": "not_yet_observed"},
        resolution_observation_ids=[],
        producer="integration-test",
    )

    rows = list(
        pg_session.scalars(
            select(BusinessNeedRevision)
            .where(BusinessNeedRevision.tenant_id == tenant_id, BusinessNeedRevision.need_id == initial.need_id)
            .order_by(BusinessNeedRevision.revision)
        )
    )
    assert [row.revision for row in rows] == [1, 2]
    assert initial.status == "recognized"
    assert initial.observation_references[0]["source_content_verification"] == "producer_attested_reference"
    assert monitoring.status == "impact_monitored"
    assert all(item["grants_execution_authority"] is False for item in monitoring.candidate_responses)

    with pytest.raises(BusinessUnderstandingValidationError, match="resolution observations"):
        service.append_need_revision(
            tenant_id=tenant_id,
            need_id=initial.need_id,
            expected_revision=2,
            origin="observed",
            status="resolved",
            subject_references=list(initial.subject_references),
            objective_reference=initial.objective_reference,
            condition_summary=initial.condition_summary,
            uncertainty=[],
            priority=initial.priority,
            confidence=0.9,
            observation_ids=[initial_observation.id, work_outcome.id],
            related_need_references=[],
            candidate_responses=[],
            proposal_references=[],
            mission_references=[],
            impact_assessment={"status": "improved"},
            resolution_observation_ids=[],
            producer="integration-test",
        )

    independently_observed_improvement = _record_acquisition_observation(
        pg_session,
        tenant_id=tenant_id,
        source_id="next-period-acquisition",
        observed_at=initial_observation.observed_at + timedelta(days=31),
    )
    resolved = service.append_need_revision(
        tenant_id=tenant_id,
        need_id=initial.need_id,
        expected_revision=2,
        origin="observed",
        status="resolved",
        subject_references=list(initial.subject_references),
        objective_reference=initial.objective_reference,
        condition_summary=initial.condition_summary,
        uncertainty=[],
        priority=initial.priority,
        confidence=0.9,
        observation_ids=[initial_observation.id, work_outcome.id, independently_observed_improvement.id],
        related_need_references=[],
        candidate_responses=[],
        proposal_references=[],
        mission_references=[],
        impact_assessment={"status": "improved", "evaluation_basis": "later_verified_measurement"},
        resolution_observation_ids=[independently_observed_improvement.id],
        producer="integration-test",
    )
    assert resolved.status == "resolved"
    assert resolved.revision == 3
    assert resolved.impact_assessment is not None
    assert resolved.impact_assessment["condition_fingerprint"].startswith("sha256:")


def test_resolution_requires_matching_subject_and_later_independent_observation(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    service = BusinessUnderstandingService(pg_session)
    initial_observation = _record_acquisition_observation(pg_session, tenant_id=tenant_id, source_id="initial")
    initial = _initial_need(service, tenant_id=tenant_id, observation_id=initial_observation.id)
    unrelated = service.record_observation(
        tenant_id=tenant_id,
        source=SourceReference(
            source_kind="external_provider",
            reference={"source_id": "different-business", "provider": "fixture-metrics"},
        ),
        observation_summary="A different business improved after an unrelated measurement.",
        subject_references=[{"kind": "organization", "id": "other"}],
        observed_at=initial_observation.observed_at + timedelta(days=31),
        confidence=0.9,
        limitations=[],
        producer="integration-test",
    )

    with pytest.raises(BusinessUnderstandingValidationError, match="need subject"):
        service.append_need_revision(
            tenant_id=tenant_id,
            need_id=initial.need_id,
            expected_revision=1,
            origin="observed",
            status="resolved",
            subject_references=list(initial.subject_references),
            objective_reference=initial.objective_reference,
            condition_summary=initial.condition_summary,
            uncertainty=[],
            priority=initial.priority,
            confidence=0.9,
            observation_ids=[initial_observation.id, unrelated.id],
            related_need_references=[],
            candidate_responses=[],
            proposal_references=[],
            mission_references=[],
            impact_assessment={"status": "improved", "evaluation_basis": "later_measurement"},
            resolution_observation_ids=[unrelated.id],
            producer="integration-test",
        )


def test_need_assessment_separates_evidence_from_capability_and_execution(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    observation = _record_acquisition_observation(pg_session, tenant_id=tenant_id, source_id="acquisition-kpi")
    need = _initial_need(BusinessUnderstandingService(pg_session), tenant_id=tenant_id, observation_id=observation.id)
    assessment = BusinessNeedReasoningService(BusinessUnderstandingRepository(pg_session)).assess(
        tenant_id=tenant_id,
        need_id=need.need_id,
        revision=need.revision,
        producer="integration-test",
        request=NeedAssessmentRequest(
            goal=Goal(
                goal_id="customer-acquisition",
                objective_key="customer_acquisition",
                name="Acquire customers",
                subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="self")],
            ),
            kpis=(
                Kpi(
                    kpi_id="qualified-leads",
                    goal_id="customer-acquisition",
                    name="Qualified leads",
                    metric="qualified_leads",
                    direction=KpiDirection.INCREASE,
                    current_value=2,
                    target_value=10,
                    previous_value=3,
                ),
            ),
            hypotheses=(
                NeedCauseHypothesis(
                    cause_key="lead_quality",
                    summary="Lead quality may be below the intended market fit.",
                    supporting_observation_ids=(observation.id,),
                ),
                NeedCauseHypothesis(
                    cause_key="pricing",
                    summary="Pricing remains unverified.",
                ),
            ),
            candidate_responses=(
                NeedCandidateResponse(
                    response_key="investigate_lead_quality",
                    summary="Investigate lead-quality evidence before selecting a channel response.",
                    requested_outcomes=("evaluate_goal_progress",),
                    supporting_observation_ids=(observation.id,),
                ),
                NeedCandidateResponse(
                    response_key="evaluate_product_gap",
                    summary="Evaluate product readiness even though no catalog outcome exists yet.",
                    requested_outcomes=("evaluate_product_readiness",),
                ),
            ),
        ),
    )
    assert assessment.goal_evaluation is not None
    assert assessment.goal_evaluation.status.value == "off_track"
    assert assessment.causes[0].status == "supported"
    assert assessment.causes[1].status == "unresolved"
    assert assessment.candidate_responses[0].capability_status == "catalog_supported"
    assert assessment.candidate_responses[1].capability_status == "unmapped"
    assert assessment.grants_execution_authority is False
    assert assessment.recommended_next_step == "consider_response"


def test_supported_response_can_be_recommended_when_the_catalog_has_no_capability(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    observation = _record_acquisition_observation(pg_session, tenant_id=tenant_id, source_id="product-readiness")
    need = _initial_need(BusinessUnderstandingService(pg_session), tenant_id=tenant_id, observation_id=observation.id)

    assessment = BusinessNeedReasoningService(BusinessUnderstandingRepository(pg_session)).assess(
        tenant_id=tenant_id,
        need_id=need.need_id,
        revision=need.revision,
        producer="integration-test",
        request=NeedAssessmentRequest(
            goal=Goal(
                goal_id="customer-acquisition",
                objective_key="customer_acquisition",
                name="Acquire customers",
                subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="self")],
            ),
            kpis=(
                Kpi(
                    kpi_id="qualified-leads",
                    goal_id="customer-acquisition",
                    name="Qualified leads",
                    metric="qualified_leads",
                    direction=KpiDirection.INCREASE,
                    current_value=2,
                    target_value=10,
                    previous_value=3,
                ),
            ),
            candidate_responses=(
                NeedCandidateResponse(
                    response_key="investigate_product_readiness",
                    summary="Investigate the observed product-readiness concern.",
                    requested_outcomes=("evaluate_product_readiness",),
                    supporting_observation_ids=(observation.id,),
                ),
            ),
        ),
    )

    response = assessment.candidate_responses[0]
    assert response.evidence_status == "supported"
    assert response.capability_status == "unmapped"
    assert assessment.recommended_next_step == "consider_response"
    assert assessment.grants_execution_authority is False


def test_catalog_capability_is_not_recommended_without_evidence(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    observation = _record_acquisition_observation(pg_session, tenant_id=tenant_id, source_id="kpi-only")
    need = _initial_need(BusinessUnderstandingService(pg_session), tenant_id=tenant_id, observation_id=observation.id)

    assessment = BusinessNeedReasoningService(BusinessUnderstandingRepository(pg_session)).assess(
        tenant_id=tenant_id,
        need_id=need.need_id,
        revision=need.revision,
        producer="integration-test",
        request=NeedAssessmentRequest(
            goal=Goal(
                goal_id="customer-acquisition",
                objective_key="customer_acquisition",
                name="Acquire customers",
                subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="self")],
            ),
            kpis=(
                Kpi(
                    kpi_id="qualified-leads",
                    goal_id="customer-acquisition",
                    name="Qualified leads",
                    metric="qualified_leads",
                    direction=KpiDirection.INCREASE,
                    current_value=2,
                    target_value=10,
                    previous_value=3,
                ),
            ),
            candidate_responses=(
                NeedCandidateResponse(
                    response_key="run_outreach",
                    summary="Run outreach despite no attributed causal evidence.",
                    requested_outcomes=("prepare_outreach",),
                ),
            ),
        ),
    )

    response = assessment.candidate_responses[0]
    assert response.capability_status == "catalog_supported"
    assert response.evidence_status == "unresolved"
    assert assessment.recommended_next_step == "seek_clarification"
    assert assessment.causes == ()


def test_inapplicable_qualified_knowledge_cannot_justify_a_response(pg_session) -> None:
    tenant_id = _tenant()
    activate_tenant_session(pg_session, tenant_id)
    observation = _record_acquisition_observation(pg_session, tenant_id=tenant_id, source_id="stale-knowledge")
    need = _initial_need(BusinessUnderstandingService(pg_session), tenant_id=tenant_id, observation_id=observation.id)
    # The knowledge subsystem emits UNRESOLVED when an otherwise relevant
    # proposition is stale or inapplicable.  The need layer consumes that
    # bounded result; it does not reinterpret it as support.
    knowledge_support = KnowledgeDecisionSupportResult.model_construct(
        support_id="knowledge-support:inapplicable",
        decision_id="need-response-evaluation",
        influences=(
            KnowledgeDecisionInfluence.model_construct(
                influence_id="knowledge-influence:inapplicable",
                option_id="run_outreach",
                direction=KnowledgeInfluenceDirection.UNRESOLVED,
            ),
        ),
        epistemic_limits=("knowledge_inapplicable",),
    )

    assessment = BusinessNeedReasoningService(BusinessUnderstandingRepository(pg_session)).assess(
        tenant_id=tenant_id,
        need_id=need.need_id,
        revision=need.revision,
        producer="integration-test",
        request=NeedAssessmentRequest(
            goal=Goal(
                goal_id="customer-acquisition",
                objective_key="customer_acquisition",
                name="Acquire customers",
                subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.ORGANIZATION, object_id="self")],
            ),
            kpis=(
                Kpi(
                    kpi_id="qualified-leads",
                    goal_id="customer-acquisition",
                    name="Qualified leads",
                    metric="qualified_leads",
                    direction=KpiDirection.INCREASE,
                    current_value=2,
                    target_value=10,
                    previous_value=3,
                ),
            ),
            candidate_responses=(
                NeedCandidateResponse(
                    response_key="run_outreach",
                    summary="A catalog response that stale knowledge cannot justify.",
                    requested_outcomes=("prepare_outreach",),
                ),
            ),
            knowledge_support=knowledge_support,
        ),
    )

    response = assessment.candidate_responses[0]
    assert response.capability_status == "catalog_supported"
    assert response.knowledge_support_status == "unresolved"
    assert response.evidence_status == "unresolved"
    assert assessment.recommended_next_step == "seek_clarification"


def test_need_revision_conflict_and_cross_tenant_observation_fail_closed(pg_session) -> None:
    tenant_a, tenant_b = _tenant(), _tenant()
    activate_tenant_session(pg_session, tenant_a)
    service_a = BusinessUnderstandingService(pg_session)
    observation = _record_acquisition_observation(pg_session, tenant_id=tenant_a, source_id="a")
    need = _initial_need(service_a, tenant_id=tenant_a, observation_id=observation.id)

    with pytest.raises(BusinessNeedRevisionConflict) as conflict:
        service_a.append_need_revision(
            tenant_id=tenant_a,
            need_id=need.need_id,
            expected_revision=0,
            origin="observed",
            status="monitoring",
            subject_references=[],
            objective_reference=None,
            condition_summary="stale writer",
            uncertainty=[],
            priority=None,
            confidence=None,
            observation_ids=[observation.id],
            related_need_references=[],
            candidate_responses=[],
            proposal_references=[],
            mission_references=[],
            impact_assessment=None,
            resolution_observation_ids=[],
            producer="integration-test",
        )
    assert conflict.value.current_revision == 1

    activate_tenant_session(pg_session, tenant_b)
    foreign_mission = Mission(
        tenant_id=tenant_b,
        objective="Foreign tenant mission",
        status="planned",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={},
    )
    MissionRepository(pg_session).add(foreign_mission)
    with pytest.raises(BusinessUnderstandingValidationError, match="observation reference"):
        _initial_need(BusinessUnderstandingService(pg_session), tenant_id=tenant_b, observation_id=observation.id)

    activate_tenant_session(pg_session, tenant_a)
    with pytest.raises(BusinessUnderstandingValidationError, match="mission reference"):
        service_a.append_need_revision(
            tenant_id=tenant_a,
            need_id=need.need_id,
            expected_revision=1,
            origin="observed",
            status="monitoring",
            subject_references=list(need.subject_references),
            objective_reference=need.objective_reference,
            condition_summary=need.condition_summary,
            uncertainty=list(need.uncertainty),
            priority=need.priority,
            confidence=need.confidence,
            observation_ids=[observation.id],
            related_need_references=[],
            candidate_responses=list(need.candidate_responses),
            proposal_references=[],
            mission_references=[{"mission_id": str(foreign_mission.id)}],
            impact_assessment=None,
            resolution_observation_ids=[],
            producer="integration-test",
        )


def test_two_sessions_cannot_commit_the_same_need_revision(pg_engine) -> None:
    tenant_id = _tenant()
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as setup:
        activate_tenant_session(setup, tenant_id)
        observation = _record_acquisition_observation(setup, tenant_id=tenant_id, source_id="concurrency")
        need = _initial_need(BusinessUnderstandingService(setup), tenant_id=tenant_id, observation_id=observation.id)
        setup.commit()

    first = factory()
    second = factory()
    try:
        activate_tenant_session(first, tenant_id)
        activate_tenant_session(second, tenant_id)
        first_seen = BusinessUnderstandingRepository(first).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need.need_id
        )
        second_seen = BusinessUnderstandingRepository(second).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need.need_id
        )
        assert first_seen is not None and second_seen is not None
        service_first = BusinessUnderstandingService(first)
        service_second = BusinessUnderstandingService(second)
        service_first.append_need_revision(
            tenant_id=tenant_id,
            need_id=need.need_id,
            expected_revision=first_seen.revision,
            origin="observed",
            status="monitoring",
            subject_references=list(need.subject_references),
            objective_reference=need.objective_reference,
            condition_summary=need.condition_summary,
            uncertainty=list(need.uncertainty),
            priority=need.priority,
            confidence=need.confidence,
            observation_ids=[observation.id],
            related_need_references=[],
            candidate_responses=list(need.candidate_responses),
            proposal_references=[],
            mission_references=[],
            impact_assessment=None,
            resolution_observation_ids=[],
            producer="first-session",
        )
        first.commit()

        with pytest.raises(BusinessNeedRevisionConflict) as conflict:
            service_second.append_need_revision(
                tenant_id=tenant_id,
                need_id=need.need_id,
                expected_revision=second_seen.revision,
                origin="observed",
                status="monitoring",
                subject_references=list(need.subject_references),
                objective_reference=need.objective_reference,
                condition_summary=need.condition_summary,
                uncertainty=list(need.uncertainty),
                priority=need.priority,
                confidence=need.confidence,
                observation_ids=[observation.id],
                related_need_references=[],
                candidate_responses=list(need.candidate_responses),
                proposal_references=[],
                mission_references=[],
                impact_assessment=None,
                resolution_observation_ids=[],
                producer="second-session",
            )
        assert conflict.value.current_revision == 2
        second.rollback()
    finally:
        first.close()
        second.close()


def test_rls_hides_business_understanding_without_tenant_context(pg_engine) -> None:
    tenant = _tenant()
    role = f"business_understanding_test_{uuid.uuid4().hex}"
    quoted_role = f'"{role}"'
    with pg_engine.begin() as admin:
        admin.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))
        admin.execute(text(f"GRANT USAGE ON SCHEMA public TO {quoted_role}"))
        admin.execute(
            text(
                f"GRANT SELECT, INSERT, UPDATE ON business_measurements, business_observations, "
                f"business_need_revisions TO {quoted_role}"
            )
        )
    try:
        with pg_engine.connect() as connection:
            connection.execute(text(f"SET ROLE {quoted_role}"))
            session = Session(bind=connection, expire_on_commit=False)
            activate_tenant_session(session, tenant)
            observation = _record_acquisition_observation(session, tenant_id=tenant, source_id="rls")
            _initial_need(BusinessUnderstandingService(session), tenant_id=tenant, observation_id=observation.id)
            session.commit()

            # A distinct tenant context cannot see tenant A, and an unset
            # context cannot read or write through the RLS policy either.
            other_tenant = _tenant()
            activate_tenant_session(session, other_tenant)
            assert BusinessUnderstandingRepository(session).list_observations_for_tenant(tenant_id=tenant) == []
            session.execute(text("RESET app.current_tenant_id"))
            assert BusinessUnderstandingRepository(session).list_observations_for_tenant(tenant_id=tenant) == []
            with pytest.raises(DBAPIError):
                _record_acquisition_observation(session, tenant_id=tenant, source_id="blocked")
            session.rollback()
            with pytest.raises(DBAPIError):
                _ingest_customer_measurement(
                    session,
                    tenant_id=tenant,
                    current=2,
                    previous=3,
                    source_version="blocked-v1",
                    period_start=datetime(2026, 5, 1, tzinfo=UTC),
                    period_end=datetime(2026, 5, 31, tzinfo=UTC),
                )
            session.rollback()
            session.close()
            connection.execute(text("RESET ROLE"))
            connection.commit()
    finally:
        with pg_engine.begin() as admin:
            admin.execute(text(f"DROP OWNED BY {quoted_role}"))
            admin.execute(text(f"DROP ROLE IF EXISTS {quoted_role}"))


def test_business_understanding_migration_preserves_populated_existing_tenant_data(pg_engine) -> None:
    """Upgrade from the prior head without disturbing existing tenant records."""

    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", str(pg_engine.url))
    tenant_id = _tenant()

    alembic_command.downgrade(config, "0054_merge_roles_evidence")
    with Session(pg_engine, expire_on_commit=False) as legacy_session:
        activate_tenant_session(legacy_session, tenant_id)
        profile = BusinessProfile(
            tenant_id=tenant_id,
            approved_facts={"business_name": {"value": "Existing tenant business"}},
            provenance={"seed": "migration-compatibility-proof"},
        )
        BusinessProfileRepository(legacy_session).add_profile(profile)
        legacy_session.commit()

    alembic_command.upgrade(config, "head")
    with Session(pg_engine, expire_on_commit=False) as upgraded_session:
        activate_tenant_session(upgraded_session, tenant_id)
        restored = BusinessProfileRepository(upgraded_session).get_active_profile_for_tenant(tenant_id=tenant_id)
        assert restored is not None
        assert restored.approved_facts["business_name"]["value"] == "Existing tenant business"


def test_upgrade_from_original_published_0057_creates_secured_measurement_schema(pg_engine) -> None:
    """0058 repairs databases where the original 0057 had no measurement table."""

    config = AlembicConfig("alembic.ini")
    config.set_main_option("sqlalchemy.url", str(pg_engine.url))
    alembic_command.downgrade(config, "0056_business_need_assessments")
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE business_need_assessments ADD CONSTRAINT "
                "uq_business_need_assessments_retry UNIQUE "
                "(tenant_id, need_id, need_revision, assessment_fingerprint)"
            )
        )
    alembic_command.stamp(config, "0057_assessment_retry_dedup")
    assert not inspect(pg_engine).has_table("business_measurements")

    alembic_command.upgrade(config, "head")
    inspector = inspect(pg_engine)
    assert inspector.has_table("business_measurements")
    assert "measurement_fingerprint" in {column["name"] for column in inspector.get_columns("business_observations")}
    assert "uq_business_measurements_ingestion_identity" in {
        item["name"] for item in inspector.get_unique_constraints("business_measurements")
    }
    with pg_engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                    "WHERE oid = 'business_measurements'::regclass"
                )
            )
            is True
        )
