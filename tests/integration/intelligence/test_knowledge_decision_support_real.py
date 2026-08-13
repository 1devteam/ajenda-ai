from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from backend.services.ontology.commercial_state import GoalSemanticSignature
from backend.services.ontology.types import BusinessObjectSemanticSignature, BusinessObjectType
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ToolInvocation
from tests.integration.intelligence.test_knowledge_retrieval_real import (
    _context,
    _qualification,
    _replace_proposition,
    _tenant_counts,
)

pytestmark = pytest.mark.integration


def test_real_ledger_to_knowledge_informed_decision_is_deterministic_and_tenant_scoped(pg_engine) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other_tenant = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)
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
        _context(tenant, factory),
    )
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

    first = registry.invoke(invocation, _context(tenant, factory))
    replay = registry.invoke(invocation, _context(tenant, factory))
    influences = first.output["support"]["influences"]
    supported = [item for item in influences if item["direction"] == "supports"]
    assert [(item["option_id"], item["criterion_id"]) for item in supported] == [("discovery", "conversion")]
    assert first.output["support"]["support_id"] == replay.output["support"]["support_id"]
    assert first.output["support"]["is_policy"] is False
    assert first.output["support"]["is_execution_instruction"] is False
    assert first.evidence[0].lineage.origin_type.value == "derived_fact"
    assert first.evidence[0].provenance["is_independent_observation"] is False
    assert first.output["decision_result"]["algorithm"]["name"] == "weighted_criterion_evidence_v1"
    assert _tenant_counts(factory, tenant) == before == (1, 1)

    hidden = registry.invoke(invocation, _context(other_tenant, factory))
    assert hidden.output["support"]["influences"] == []
    assert _tenant_counts(factory, tenant) == before
