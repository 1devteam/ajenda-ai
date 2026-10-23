"""PostgreSQL proof for business-understanding persistence and isolation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command as alembic_command
from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_profile import BusinessProfile
from backend.domain.business_understanding import BusinessNeedRevision, BusinessObservation
from backend.domain.mission import Mission
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.business_understanding_repository import (
    BusinessNeedRevisionConflict,
    BusinessUnderstandingRepository,
)
from backend.repositories.mission_repository import MissionRepository
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
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectType

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
            text(f"GRANT SELECT, INSERT, UPDATE ON business_observations, business_need_revisions TO {quoted_role}")
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
