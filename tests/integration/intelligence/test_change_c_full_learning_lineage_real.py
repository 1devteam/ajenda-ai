"""Single-lineage Change C acceptance proof on PostgreSQL and the canonical worker path.

The measurements are explicitly customer-attested fixture observations. Qualification
is earned, not hand-inserted; no external verification or causation is claimed.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.mission import Mission
from backend.domain.tenant import Tenant
from backend.repositories.business_understanding_repository import BusinessUnderstandingRepository
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.decision_feedback import DecisionLearningSignal
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ToolInvocation
from tests.integration.intelligence.canonical_decision_runtime import (
    EXECUTION_ACTION,
    MATERIALIZATION_ACTION,
    execute_canonical_action,
    materialize_canonical_decision_episode,
    seed_execution_authority,
)
from tests.integration.intelligence.test_knowledge_retrieval_real import _context, _tenant_counts
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration


def test_change_c_measurements_earn_knowledge_and_inform_subsequent_decision(
    pg_engine, queue_adapter, redis_client
) -> None:
    tenant, other_tenant = str(uuid.uuid4()), str(uuid.uuid4())
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as session:
        session.add_all(
            [
                Tenant(id=uuid.UUID(tenant), name="Change C lineage", slug=f"change-c-{tenant[:8]}", plan="free"),
                Tenant(id=uuid.UUID(other_tenant), name="Isolated tenant", slug=f"other-{other_tenant[:8]}", plan="free"),
            ]
        )
        session.commit()

    # Each episode has its own subject, measurement source, mission, runtime
    # decision, authorized execution, outcome and durable learning signal.
    episodes = [
        materialize_canonical_decision_episode(
            factory=factory,
            queue_adapter=queue_adapter,
            tenant_id=tenant,
            index=index,
            measurement_backed=True,
        )
        for index in (301, 302, 303)
    ]
    episode_ids = {item.learning_signal.episode_reference.episode_id for item in episodes}
    signal_evidence_ids = {str(item.learning_signal_evidence_id) for item in episodes}
    assert len(episode_ids) == len(signal_evidence_ids) == 3
    assert len({item.mission_id for item in episodes}) == 3
    assert len({item.baseline_measurement_id for item in episodes}) == 3
    assert len({item.later_measurement_id for item in episodes}) == 3

    with factory() as session:
        activate_tenant_session(session, tenant)
        for item in episodes:
            assert item.need_id is not None and item.impact_revision_id is not None
            assert item.baseline_measurement_id is not None and item.later_measurement_id is not None
            repo = BusinessUnderstandingRepository(session)
            baseline = repo.get_measurement_for_tenant(
                tenant_id=tenant, measurement_id=item.baseline_measurement_id
            )
            later = repo.get_measurement_for_tenant(
                tenant_id=tenant, measurement_id=item.later_measurement_id
            )
            revision = repo.get_latest_need_for_tenant(tenant_id=tenant, need_id=item.need_id)
            assert baseline is not None and later is not None and revision is not None
            assert baseline.source_kind == later.source_kind == "customer_attested"
            assert revision.id == item.impact_revision_id
            assert revision.impact_assessment is not None
            assert revision.impact_assessment["outcome_evidence_id"] == str(item.outcome_evidence_id)
            assert revision.impact_assessment["baseline_measurement_id"] == str(baseline.id)
            assert revision.impact_assessment["observed_measurement_id"] == str(later.id)
            assert revision.impact_assessment["causation"] == "unresolved"

    registry = get_default_action_registry(rebuild=True)
    invocation = ToolInvocation(action="knowledge.consolidate_learning_history", input={})
    consolidated = registry.invoke(invocation, _context(tenant, factory))
    replay = registry.invoke(invocation, _context(tenant, factory))
    assert set(consolidated.output["records_inspected"]) == signal_evidence_ids
    assert len(consolidated.output["experience"]["pattern_candidates"]) == 1
    candidate = consolidated.output["experience"]["pattern_candidates"][0]
    assert set(candidate["supporting_episode_ids"]) == episode_ids
    assert candidate["recurrence"]["independent_support_count"] >= 3, candidate["recurrence"]

    assert len(consolidated.output["qualifications"]) == 1
    earned = consolidated.output["qualifications"][0]
    qualification = earned["qualification"]
    assert qualification["status"] == "qualified", qualification["gates"]
    assert set(qualification["evidence_summary"]["supporting_episode_ids"]) == episode_ids
    assert earned["ledger_write"]["status"] == "recorded"
    assert replay.output["qualifications"][0]["ledger_write"]["status"] == "already_recorded"
    assert _tenant_counts(factory, tenant) == (1, 1)
    assert _tenant_counts(factory, other_tenant) == (0, 0)
    assert registry.invoke(invocation, _context(other_tenant, factory)).output["records_inspected"] == []

    proposition = qualification["proposition"]
    assert proposition is not None and qualification["qualified_knowledge"] is not None
    scope = proposition["scope_conditions"]
    invalidation = proposition["invalidation_conditions"]
    assert scope
    mission_id = uuid.uuid4()
    current_subject = "opp-later-independent"
    subject_ref = {"object_type": "opportunity", "object_id": current_subject}
    evaluated_at = datetime.now(UTC) + timedelta(days=45)
    evaluated_text = evaluated_at.isoformat()
    conditions = [
        {
            "condition_key": condition_key,
            "state": state,
            "subject_refs": [subject_ref],
            "observed_at": evaluated_text,
            "verification_basis": "source_supplied_under_contract",
        }
        for state, keys in (("active", scope), ("inactive", invalidation))
        for condition_key in keys
    ]

    with factory() as session:
        session.add(Mission(id=mission_id, tenant_id=tenant, objective="Next decision informed by prior results"))
        session.flush()
        activate_tenant_session(session, tenant)
        persist_test_operating_charter(session, tenant_id=tenant)
        TenantInternalRecordRepository(session).write_record(
            tenant_id=tenant,
            record_type="opportunity",
            record_id=current_subject,
            data={"name": "Next opportunity", "condition_observations": conditions},
        )
        session.commit()

    source = execute_canonical_action(
        factory=factory,
        queue_adapter=queue_adapter,
        tenant_id=tenant,
        mission_id=mission_id,
        action="record.read",
        action_input={"record_type": "opportunity", "record_id": current_subject},
        worker_label="change-c-applicability",
    )
    options = [
        {"option_id": "followup", "label": "Follow up", "intervention_key": EXECUTION_ACTION},
        {"option_id": "research", "label": "Research", "intervention_key": "record.search"},
    ]
    criteria = [{"criterion_id": "conversion", "label": "Conversion", "weight": 1.0, "required": False}]
    goal_semantics = GoalSemanticSignature(objective_key="increase_conversion").model_dump(mode="json")
    subjects = [BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY).model_dump(mode="json")]
    input_data = {
        "decision_id": "change-c-later-decision",
        "decision": {"goal": "Increase conversion", "options": options, "criteria": criteria},
        "options": options,
        "criteria": [{**criteria[0], "objective_key": "increase_conversion"}],
        "query": {"subject_semantic_signatures": subjects, "goal_semantic_signature": goal_semantics},
        "applicability_context": {
            "subject_refs": [subject_ref],
            "subject_semantic_signatures": subjects,
            "goal_semantic_signature": goal_semantics,
            "condition_assertions": [
                {**condition, "evidence_ids": [str(source.id)]} for condition in conditions
            ],
            "evaluated_at": evaluated_text,
        },
    }
    context = _context(tenant, factory).model_copy(update={"mission_id": mission_id})
    without_knowledge = registry.invoke(
        ToolInvocation(action="decision.recommend_next_action", input=input_data["decision"]), context
    )
    with_knowledge = registry.invoke(
        ToolInvocation(action="knowledge.inform_decision", input=input_data), context
    )
    support = [
        item for item in with_knowledge.output["support"]["influences"]
        if item["direction"] == "supports"
    ]
    assert [(item["option_id"], item["criterion_id"]) for item in support] == [("followup", "conversion")]
    assert set(support[0]["supporting_episode_ids"]) == episode_ids
    assert qualification["qualification_id"] in support[0]["qualification_ids"]
    assert without_knowledge.output["recommendation"] == "gather_more_evidence"
    assert with_knowledge.output["decision_result"]["recommendation"] == "followup"
    assert with_knowledge.output["support"]["is_policy"] is False
    assert with_knowledge.output["support"]["is_execution_instruction"] is False
    assert set(with_knowledge.output["decision_result"]["supporting_evidence_ids"]) == signal_evidence_ids

    # Reuse must also survive durable queue execution and later materialization;
    # no direct knowledge action is allowed to grant execution authority.
    recommended = execute_canonical_action(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant,
        mission_id=mission_id, action="knowledge.inform_decision",
        action_input=input_data, worker_label="change-c-knowledge-decision",
    )
    execution = execute_canonical_action(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, mission_id=mission_id,
        action=EXECUTION_ACTION,
        action_input={
            "record_type": "activity",
            "record_id": "change-c-later-execution",
            "data": {"status": "completed", "subject_id": current_subject},
        },
        worker_label="change-c-execution",
        runtime_authority_metadata=seed_execution_authority(factory=factory, tenant_id=tenant),
    )
    executed_at = datetime.fromisoformat(str(execution.structured_payload["executed_at"]))
    outcome = execute_canonical_action(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, mission_id=mission_id,
        action="analysis.evaluate_outcome",
        action_input={
            "goal": {
                "goal_id": "goal-increase-conversion",
                "objective_key": "increase_conversion",
                "name": "Increase conversion",
                "subject_refs": [subject_ref],
            },
            "subject_refs": [subject_ref],
            "baseline_kpis": [{
                "kpi_id": "conversion", "goal_id": "goal-increase-conversion",
                "name": "Conversion", "metric": "conversion",
                "current_value": 0.5, "target_value": 1.0,
            }],
            "observed_kpis": [{
                "kpi_id": "conversion", "goal_id": "goal-increase-conversion",
                "name": "Conversion", "metric": "conversion",
                "current_value": 1.0, "target_value": 1.0,
            }],
            "source_observed_at": (executed_at + timedelta(milliseconds=1)).isoformat(),
            "evidence_ids": [str(execution.id)],
        },
        worker_label="change-c-next-outcome",
    )
    learned = execute_canonical_action(
        factory=factory, queue_adapter=queue_adapter, tenant_id=tenant, mission_id=mission_id,
        action=MATERIALIZATION_ACTION,
        action_input={
            "recommendation_evidence_id": str(recommended.id),
            "outcome_evaluation_evidence_id": str(outcome.id),
            "execution_evidence_ids": [str(execution.id)],
        },
        worker_label="change-c-next-learning",
    )
    next_signal = DecisionLearningSignal.model_validate(learned.structured_payload)
    assert next_signal.episode_reference is not None
    assert set(next_signal.supporting_evidence_ids) == signal_evidence_ids | {str(execution.id)}

    manifest_dir = os.getenv("CHANGE_C_EVIDENCE_MANIFEST_DIR")
    if manifest_dir:
        location = Path(manifest_dir)
        location.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "test_fixture_only": True,
            "customer_attested_not_externally_verified": True,
            "commit_sha": os.getenv("GITHUB_SHA"),
            "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
            "tenant_scope": "isolated_fixture",
            "historical_episodes": [
                {
                    "baseline_measurement_id": str(item.baseline_measurement_id),
                    "later_measurement_id": str(item.later_measurement_id),
                    "need_id": item.need_id,
                    "impact_revision_id": str(item.impact_revision_id),
                    "mission_id": str(item.mission_id),
                    "outcome_evidence_id": str(item.outcome_evidence_id),
                    "learning_signal_evidence_id": str(item.learning_signal_evidence_id),
                    "episode_id": item.learning_signal.episode_reference.episode_id,
                }
                for item in episodes
            ],
            "qualification_id": qualification["qualification_id"],
            "qualification_gates": qualification["gates"],
            "qualification_status": qualification["status"],
            "knowledge_id": qualification["qualified_knowledge"]["knowledge_id"],
            "baseline_recommendation": without_knowledge.output["recommendation"],
            "informed_recommendation": with_knowledge.output["decision_result"]["recommendation"],
            "later_recommendation_evidence_id": str(recommended.id),
            "later_execution_evidence_id": str(execution.id),
            "later_outcome_evidence_id": str(outcome.id),
            "later_learning_signal_evidence_id": str(learned.id),
            "causal_contribution_proven": False,
        }
        (location / "change-c-lineage-proof.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
