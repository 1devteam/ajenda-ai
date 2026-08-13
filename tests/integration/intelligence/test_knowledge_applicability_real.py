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


def test_real_ledger_lifecycle_retrieval_applicability_is_read_only_and_tenant_scoped(pg_engine) -> None:
    tenant = f"tenant-{uuid.uuid4()}"
    other_tenant = f"tenant-{uuid.uuid4()}"
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    registry = get_default_action_registry(rebuild=True)
    qualification = _replace_proposition(
        _qualification(intervention="sales.schedule_discovery", indexes=(101, 102, 103)),
        scope_conditions=("segment:smb",),
        invalidation_conditions=("pricing_model_changed",),
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
    query = {
        "subject_semantic_signatures": [
            BusinessObjectSemanticSignature(object_type=BusinessObjectType.OPPORTUNITY).model_dump(mode="json")
        ],
        "goal_semantic_signature": GoalSemanticSignature(objective_key="increase_conversion").model_dump(mode="json"),
    }

    def invoke(scope_state: str, invalidation_state: str, active_tenant: str = tenant):
        return registry.invoke(
            ToolInvocation(
                action="knowledge.evaluate_applicability",
                input={
                    "query": query,
                    "context": {
                        "subject_refs": [{"object_type": "opportunity", "object_id": "opp-123"}],
                        "subject_semantic_signatures": query["subject_semantic_signatures"],
                        "goal_semantic_signature": query["goal_semantic_signature"],
                        "condition_assertions": [
                            {
                                "condition_key": "segment:smb",
                                "state": scope_state,
                                "subject_refs": [{"object_type": "opportunity", "object_id": "opp-123"}],
                                "evidence_ids": ["ev-crm-segment"],
                                "observed_at": now,
                                "verification_basis": "source_supplied_under_contract",
                            },
                            {
                                "condition_key": "pricing_model_changed",
                                "state": invalidation_state,
                                "subject_refs": [{"object_type": "opportunity", "object_id": "opp-123"}],
                                "evidence_ids": ["ev-pricing-version"],
                                "observed_at": now,
                                "verification_basis": "independently_verified",
                            },
                        ],
                        "evaluated_at": now,
                    },
                },
            ),
            _context(active_tenant, factory),
        )

    applicable = invoke("active", "inactive")
    assert applicable.output["evaluations"][0]["status"] == "applicable"
    assert applicable.output["retrieval"]["matches"][0]["applicability_determined"] is False
    assert applicable.evidence[0].structured_payload["referenced_evidence_ids"] == [
        "ev-crm-segment",
        "ev-pricing-version",
    ]
    assert all(not item.startswith("evidence:") for item in applicable.records_inspected)
    assert invoke("unknown", "inactive").output["evaluations"][0]["status"] == "insufficient_context"
    assert invoke("active", "active").output["evaluations"][0]["status"] == "invalidated"
    assert _tenant_counts(factory, tenant) == before == (1, 1)

    hidden = invoke("active", "inactive", other_tenant)
    assert hidden.output["evaluations"] == []
    assert hidden.output["reason_codes"] == ["no_current_semantic_knowledge_match"]
    assert _tenant_counts(factory, tenant) == before
