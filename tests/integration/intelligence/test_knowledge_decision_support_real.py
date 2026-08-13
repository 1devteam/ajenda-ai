from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.evidence import EvidenceRecord
from backend.domain.mission import Mission
from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.decision_feedback import DecisionEpisodeReference
from backend.services.ontology.evidence_lineage import (
    EvidenceLineage,
    EvidenceLineageResolution,
    EvidenceOriginType,
)
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ToolInvocation
from tests.integration.intelligence.test_knowledge_retrieval_real import (
    _context,
    _qualification,
    _replace_proposition,
    _tenant_counts,
)
from tests.unit.ontology.test_experience_intelligence import signal

pytestmark = pytest.mark.integration


def test_real_ledger_to_knowledge_informed_decision_is_deterministic_and_tenant_scoped(pg_engine) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other_tenant = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)
    mission_id = uuid.uuid4()
    qualification = _replace_proposition(
        _qualification(intervention="sales.schedule_discovery", indexes=(201, 202, 203)),
        scope_conditions=("segment:smb",),
        invalidation_conditions=(),
    )
    registry.invoke(
        ToolInvocation(
            action="knowledge.record_qualification",
            input={"result": qualification.model_dump(mode="json")},
        ),
        _context(tenant, factory, mission_id=mission_id),
    )
    world_ids = tuple(uuid.uuid4() for _ in range(3))
    with factory() as setup:
        activate_tenant_session(setup, tenant)
        setup.add(Mission(id=mission_id, tenant_id=tenant, objective="Knowledge decision support proof"))
        setup.flush()
        for index, (episode_id, world_id) in enumerate(
            zip(qualification.evidence_summary.supporting_episode_ids, world_ids, strict=True), start=201
        ):
            world_lineage = EvidenceLineage(
                artifact_evidence_id=str(world_id),
                origin_type=EvidenceOriginType.SOURCE_OBSERVATION,
                root_evidence_ids=(str(world_id),),
                resolution=EvidenceLineageResolution.KNOWN,
            )
            owner_signal = signal(index, evidence=[str(world_id)]).model_copy(
                update={
                    "episode_reference": DecisionEpisodeReference(
                        episode_id=episode_id,
                        decision_id=f"decision-{index}",
                        recommendation_evidence_id=str(uuid.uuid4()),
                        mission_id=str(mission_id),
                        recommendation_execution_task_id=str(uuid.uuid4()),
                        outcome_evaluation_evidence_id=str(world_id),
                    ),
                    "evidence_lineages": (world_lineage,),
                }
            )
            setup.add_all(
                [
                    EvidenceRecord(
                        id=world_id,
                        tenant_id=tenant,
                        mission_id=mission_id,
                        evidence_type="source_observation",
                        evidence_source="crm",
                        summary="Independent world outcome",
                        structured_payload={},
                        provenance_metadata={"evidence_lineage": world_lineage.model_dump(mode="json")},
                    ),
                    EvidenceRecord(
                        tenant_id=tenant,
                        mission_id=mission_id,
                        evidence_type="execution_trace",
                        evidence_source="decision_episode_materialization",
                        summary="Durable decision learning signal",
                        structured_payload=owner_signal.model_dump(mode="json"),
                        provenance_metadata={
                            "action_name": "analysis.materialize_decision_learning_signal",
                            "evidence_role": "decision_learning_signal",
                        },
                    ),
                ]
            )
        setup.commit()
    before = _tenant_counts(factory, tenant)
    now = datetime(2026, 8, 13, tzinfo=UTC).isoformat()
    subject_semantics = [
        BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY).model_dump(mode="json")
    ]
    goal_semantics = GoalSemanticSignature(objective_key="increase_conversion").model_dump(mode="json")
    options = [
        {
            "option_id": "discovery",
            "label": "Schedule discovery",
            "intervention_key": "sales.schedule_discovery",
        },
        {
            "option_id": "pricing",
            "label": "Send pricing",
            "intervention_key": "sales.send_pricing",
        },
    ]
    decision_criteria = [{"criterion_id": "conversion", "label": "Conversion", "weight": 1.0}]
    support_criteria = [
        {
            **decision_criteria[0],
            "objective_key": "increase_conversion",
        }
    ]
    invocation = ToolInvocation(
        action="knowledge.inform_decision",
        input={
            "decision_id": "decision-real-430",
            "decision": {
                "goal": "Increase conversion",
                "options": options,
                "criteria": decision_criteria,
            },
            "options": options,
            "criteria": support_criteria,
            "query": {
                "subject_semantic_signatures": subject_semantics,
                "goal_semantic_signature": goal_semantics,
            },
            "applicability_context": {
                "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
                "subject_semantic_signatures": subject_semantics,
                "goal_semantic_signature": goal_semantics,
                "condition_assertions": [
                    {
                        "condition_key": "segment:smb",
                        "state": "active",
                        "subject_refs": [{"object_type": "opportunity", "object_id": "opp-real-430"}],
                        "evidence_ids": ["world-outcome-root-a"],
                        "observed_at": now,
                        "verification_basis": "independently_verified",
                    }
                ],
                "evaluated_at": now,
            },
        },
    )

    first = registry.invoke(invocation, _context(tenant, factory, mission_id=mission_id))
    replay = registry.invoke(invocation, _context(tenant, factory, mission_id=mission_id))
    influences = first.output["support"]["influences"]
    supported = [item for item in influences if item["direction"] == "supports"]
    assert [(item["option_id"], item["criterion_id"]) for item in supported] == [("discovery", "conversion")]
    assert first.output["support"]["support_id"] == replay.output["support"]["support_id"]
    assert first.output["support"]["is_policy"] is False
    assert first.output["support"]["is_execution_instruction"] is False
    assert first.evidence[0].lineage.origin_type.value == "derived_fact"
    assert first.evidence[0].provenance["is_independent_observation"] is False
    assert first.output["decision_result"]["algorithm"]["name"] == "weighted_criterion_evidence_v1"
    assert first.output["decision_result"]["recommendation"] == "discovery"
    assert first.output["decision_result"]["knowledge_decision_support"]["applied_influence_ids"]
    assert set(first.output["decision_result"]["supporting_evidence_ids"]) == {str(item) for item in world_ids}
    assert all(
        not identity.startswith("knowledge-influence-v1:")
        for row in first.output["decision_result"]["option_scores"]
        for identity in row["supporting_evidence_ids"]
    )
    assert first.evidence[0].lineage.root_evidence_ids == tuple(sorted(str(item) for item in world_ids))
    assert _tenant_counts(factory, tenant) == before == (1, 1)

    hidden = registry.invoke(invocation, _context(other_tenant, factory, mission_id=mission_id))
    assert hidden.output["support"]["influences"] == []
    assert _tenant_counts(factory, tenant) == before
