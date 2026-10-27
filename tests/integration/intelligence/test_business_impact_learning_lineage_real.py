"""Real Layer-3B proof: business impact becomes qualified, applicable knowledge.

The fixture deliberately exercises existing owners only.  A selected response
is provenance, later measurements are independently ingested, and the final
Decision is read-only support rather than an execution instruction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.business_understanding import BusinessMeasurement, BusinessNeedAssessment, BusinessNeedRevision
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.business_understanding.service import BusinessUnderstandingService
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.ontology.commercial_state import Goal, GoalSemanticSignature, Kpi
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.types import BusinessObjectRef, BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ToolInvocation
from tests.integration.intelligence.canonical_decision_runtime import execute_canonical_action
from tests.integration.intelligence.test_knowledge_retrieval_real import _context, _tenant_counts
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration


def _episode(
    *, factory, queue_adapter, tenant_id: str, index: int
) -> tuple[str, str, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create one committed Layer-2 chain and its materialized business episode."""

    subject_id = f"business-impact-{index}"
    subject = {"schema_version": 1, "object_type": "opportunity", "object_id": subject_id}
    need_id = f"need-conversion-{index}"
    goal = Goal(
        goal_id="goal-increase-conversion",
        objective_key="increase_conversion",
        name="Increase conversion",
        subject_refs=[BusinessObjectRef(object_type=BusinessObjectType.OPPORTUNITY, object_id=subject_id)],
    )
    with factory() as session:
        activate_tenant_session(session, tenant_id)
        revision = BusinessNeedRevision(
            tenant_id=tenant_id,
            need_id=need_id,
            revision=1,
            origin="observed",
            status="recognized",
            subject_references=[subject],
            objective_reference={"objective_key": "increase_conversion"},
            condition_summary="Conversion is below target.",
            uncertainty=[{"kind": "causal", "summary": "Cause is unresolved."}],
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
            assessment_fingerprint=f"sha256:{index:064x}",
            producer="test.reasoning",
            assessment_json={
                "tenant_id": tenant_id,
                "need_id": need_id,
                "need_revision": 1,
                "condition_summary": revision.condition_summary,
                "candidate_responses": [
                    {
                        "response_key": "inspect_funnel",
                        "summary": "Inspect funnel conversion.",
                        "evidence_status": "supported",
                        "knowledge_support_status": "not_provided",
                        "dependencies": [],
                        "assumptions": [],
                        "tradeoffs": [],
                    }
                ],
                "causes": [],
                "information_gaps": [],
                "supporting_observation_ids": [],
                "contradictory_observation_ids": [],
                "knowledge_epistemic_limits": [],
                "evaluated_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            },
        )
        session.add(assessment)
        baseline = BusinessMeasurement(
            tenant_id=tenant_id,
            subject_references=[subject],
            objective_key="increase_conversion",
            metric="conversion",
            values=[
                {
                    "kpi_id": "conversion",
                    "goal_id": goal.goal_id,
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
            period_start=datetime(2026, 1, 1, tzinfo=UTC),
            period_end=datetime(2026, 1, 31, tzinfo=UTC),
            observed_at=datetime(2026, 1, 31, tzinfo=UTC),
            source_kind="customer_attested",
            source_reference={"source_id": f"baseline-{index}"},
            source_version="v1",
            source_content_fingerprint=f"sha256:{index + 10:064x}",
            limitations=[{"code": "customer_attested"}],
            confidence=None,
        )
        session.add(baseline)
        session.flush()
        composition = MissionCompositionService(db=session).compose(
            tenant_id=tenant_id,
            instruction="Review the referenced business need assessment and recommend the next action.",
            business_need_reference={"need_id": need_id, "revision": 1},
            business_need_assessment_reference={
                "assessment_id": str(assessment.id),
                "selected_candidate_response_key": "inspect_funnel",
                "baseline_measurement_id": str(baseline.id),
            },
        )
        confirmed = MissionCompositionService(db=session).confirm(
            tenant_id=tenant_id,
            proposal_id=composition.proposal_id,
            idempotency_key=f"business-impact-{index}",
        )
        mission_id = uuid.UUID(confirmed["mission_id"])
        TenantInternalRecordRepository(session).write_record(
            tenant_id=tenant_id,
            record_type="opportunity",
            record_id=subject_id,
            data={"name": f"Historical opportunity {index}"},
        )
        session.commit()

    source = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": subject_id},
        worker_label=f"business-impact-source-{index}",
    )
    with factory() as session:
        activate_tenant_session(session, tenant_id)
        later, _ = BusinessUnderstandingService(session).ingest_measurement(
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
                    previous_value=0.5,
                    target_value=0.75,
                    unit="ratio",
                )
            ],
            subject_references=[subject],
            source_kind="customer_attested",
            source_reference={"source_id": f"later-{index}"},
            source_version="v2",
            measurement_period_start=datetime(2026, 2, 1, tzinfo=UTC),
            measurement_period_end=datetime(2026, 2, 28, tzinfo=UTC),
            observed_at=datetime(2026, 2, 28, tzinfo=UTC),
            successor_mission_id=mission_id,
            limitations=[{"code": "customer_attested"}],
            confidence=None,
            producer="test.measurement_intake",
        )
        current = BusinessUnderstandingRepository(session).get_latest_need_for_tenant(
            tenant_id=tenant_id, need_id=need_id
        )
        assert current is not None
        pairing = BusinessUnderstandingService(session).accept_measurement_pairing(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=current.revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later.id,
            producer="test.pairing",
        )
        session.commit()

    outcome = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": goal.model_dump(mode="json"),
            "subject_refs": [subject],
            "baseline_kpis": baseline.values,
            "observed_kpis": later.values,
            "source_observed_at": later.observed_at.isoformat(),
            "accepted_measurement_pairing_id": str(pairing.id),
            "outcome_evaluation_id": f"business-impact-outcome-{index}",
            "evidence_ids": [str(source.id)],
        },
        worker_label=f"business-impact-outcome-{index}",
    )
    with factory() as session:
        activate_tenant_session(session, tenant_id)
        impact, _ = BusinessUnderstandingService(session).record_canonical_measurement_impact(
            tenant_id=tenant_id,
            need_id=need_id,
            expected_revision=pairing.need_revision,
            baseline_measurement_id=baseline.id,
            observed_measurement_id=later.id,
            outcome_evidence_id=outcome.id,
            accepted_measurement_pairing_id=pairing.id,
            producer="test.impact",
        )
        session.commit()
    learning = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="analysis.materialize_decision_learning_signal",
        action_input={"impact_revision_id": str(impact.id)},
        worker_label=f"business-impact-learning-{index}",
    )
    signal = DecisionLearningSignal.model_validate(learning.structured_payload)
    assert signal.episode_reference is not None and signal.episode_reference.episode_kind == "business_impact"
    return (
        signal.episode_reference.episode_id,
        need_id,
        learning.id,
        mission_id,
        baseline.id,
        later.id,
        pairing.id,
    )


def test_business_impact_history_qualifies_and_informs_a_later_decision(pg_engine, queue_adapter, redis_client) -> None:
    tenant_id, other_tenant = str(uuid.uuid4()), str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Tenant(id=uuid.UUID(tenant_id), name="Business impact", slug=f"impact-{tenant_id[:8]}", plan="free"),
                Tenant(id=uuid.UUID(other_tenant), name="Other", slug=f"other-{other_tenant[:8]}", plan="free"),
            ]
        )
        session.flush()
        activate_tenant_session(session, tenant_id)
        persist_test_operating_charter(session, tenant_id=tenant_id)
        session.commit()
    episodes = [
        _episode(factory=factory, queue_adapter=queue_adapter, tenant_id=tenant_id, index=index) for index in (1, 2, 3)
    ]
    episode_ids, _, signal_ids, mission_ids, baseline_ids, later_ids, pairing_ids = zip(*episodes, strict=True)
    # The recurrence owner receives independently observable Layer-2 units,
    # rather than three retries of a single measurement or pairing.
    assert len(set(episode_ids)) == len(set(signal_ids)) == len(set(mission_ids)) == 3
    assert len(set(baseline_ids)) == len(set(later_ids)) == len(set(pairing_ids)) == 3
    registry = get_default_action_registry(rebuild=True)
    consolidated = registry.invoke(
        ToolInvocation(action="knowledge.consolidate_learning_history", input={}), _context(tenant_id, factory)
    )
    qualification = consolidated.output["qualifications"][0]["qualification"]
    assert qualification["status"] == "qualified", qualification["gates"]
    assert set(qualification["evidence_summary"]["supporting_episode_ids"]) == set(episode_ids)
    assert _tenant_counts(factory, tenant_id) == (1, 1)
    assert _tenant_counts(factory, other_tenant) == (0, 0)

    mission_id, subject_id = uuid.uuid4(), "later-opportunity"
    subject_ref = {"object_type": "opportunity", "object_id": subject_id}
    proposition = qualification["proposition"]
    evaluated_at = datetime.now(UTC) + timedelta(days=45)
    conditions = [
        {
            "condition_key": key,
            "state": state,
            "subject_refs": [subject_ref],
            "observed_at": evaluated_at.isoformat(),
            "verification_basis": "source_supplied_under_contract",
        }
        for state, keys in (
            ("active", proposition["scope_conditions"]),
            ("inactive", proposition["invalidation_conditions"]),
        )
        for key in keys
    ]
    with factory() as session:
        activate_tenant_session(session, tenant_id)
        session.add(Mission(id=mission_id, tenant_id=tenant_id, objective="Later decision using business history"))
        TenantInternalRecordRepository(session).write_record(
            tenant_id=tenant_id,
            record_type="opportunity",
            record_id=subject_id,
            data={"condition_observations": conditions},
        )
        session.commit()
    source = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant_id,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": subject_id},
        worker_label="business-impact-applicability",
    )
    subjects = [BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY).model_dump(mode="json")]
    options = [
        {"option_id": "inspect", "label": "Inspect funnel", "intervention_key": "inspect_funnel"},
        {"option_id": "research", "label": "Research", "intervention_key": "record.search"},
    ]
    criteria = [{"criterion_id": "conversion", "label": "Conversion", "weight": 1.0, "required": False}]
    input_data = {
        "decision_id": "later-business-impact-decision",
        "decision": {"goal": "Increase conversion", "options": options, "criteria": criteria},
        "options": options,
        "criteria": [{**criteria[0], "objective_key": "increase_conversion"}],
        "query": {
            "subject_semantic_signatures": subjects,
            "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_conversion").model_dump(
                mode="json"
            ),
        },
        "applicability_context": {
            "subject_refs": [subject_ref],
            "subject_semantic_signatures": subjects,
            "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_conversion").model_dump(
                mode="json"
            ),
            "condition_assertions": [{**condition, "evidence_ids": [str(source.id)]} for condition in conditions],
            "evaluated_at": evaluated_at.isoformat(),
        },
    }
    result = registry.invoke(
        ToolInvocation(action="knowledge.inform_decision", input=input_data),
        _context(tenant_id, factory).model_copy(update={"mission_id": mission_id}),
    )
    influences = [item for item in result.output["support"]["influences"] if item["direction"] == "supports"]
    assert [(item["option_id"], item["criterion_id"]) for item in influences] == [("inspect", "conversion")]
    assert set(influences[0]["supporting_episode_ids"]) == set(episode_ids)
    assert result.output["decision_result"]["recommendation"] == "inspect"
    assert set(result.output["decision_result"]["supporting_evidence_ids"]) == {str(item) for item in signal_ids}
