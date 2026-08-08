"""Unit tests for Business Ontology Slice 1 contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.ontology import (
    CANONICAL_BUSINESS_OBJECT_TYPES,
    RELATIONSHIP_SPECS,
    BusinessObjectRef,
    BusinessObjectType,
    canonicalize_object_type,
    is_canonical_object_type,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import ActionRuntimeContext, EvidenceFact, ToolInvocation
import uuid


def test_canonical_types_are_exactly_slice_1_set() -> None:
    assert CANONICAL_BUSINESS_OBJECT_TYPES == {
        "person",
        "organization",
        "account",
        "contact",
        "lead",
        "opportunity",
    }


def test_aliases_map_to_canonical() -> None:
    assert canonicalize_object_type("company") == BusinessObjectType.ORGANIZATION
    assert canonicalize_object_type("deal") == BusinessObjectType.OPPORTUNITY
    assert canonicalize_object_type("prospect") == BusinessObjectType.LEAD
    assert canonicalize_object_type("CONTACT") == BusinessObjectType.CONTACT
    assert canonicalize_object_type("account") == BusinessObjectType.ACCOUNT


def test_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown business object type"):
        canonicalize_object_type("invoice")


def test_is_canonical_object_type() -> None:
    assert is_canonical_object_type("opportunity") is True
    assert is_canonical_object_type("deal") is False


def test_business_object_ref_validates() -> None:
    ref = BusinessObjectRef(object_type=BusinessObjectType.ACCOUNT, object_id="acct-1")
    assert ref.object_type == BusinessObjectType.ACCOUNT
    assert ref.object_id == "acct-1"
    assert ref.schema_version == 1


def test_business_object_ref_rejects_blank_id() -> None:
    with pytest.raises(ValidationError):
        BusinessObjectRef(object_type=BusinessObjectType.CONTACT, object_id="  ")


def test_relationship_specs_cover_core_edges() -> None:
    names = {spec.name for spec in RELATIONSHIP_SPECS}
    assert "contact_belongs_to_account" in names
    assert "opportunity_concerns_account" in names
    assert "lead_associated_contact" in names


def test_evidence_fact_accepts_about_object_refs() -> None:
    fact = EvidenceFact(
        evidence_id="e1",
        claim="Acme is in discovery",
        status="known",
        confidence=0.9,
        supports_option_ids=["draft_followup"],
        supports_criterion_ids=["fit"],
        about_object_refs=[
            {"object_type": "opportunity", "object_id": "opp-1"},
            {"object_type": "account", "object_id": "acct-acme"},
        ],
    )
    assert len(fact.about_object_refs) == 2
    assert fact.about_object_refs[0].object_type == BusinessObjectType.OPPORTUNITY


def test_evidence_fact_without_object_refs_still_valid() -> None:
    fact = EvidenceFact(evidence_id="e2", claim="standalone claim", status="inferred")
    assert fact.about_object_refs == []


def test_decision_recommend_accepts_facts_with_object_refs() -> None:
    """Optional object refs must not break decision.recommend_next_action."""

    registry = get_default_action_registry(rebuild=True)
    context = ActionRuntimeContext(
        tenant_id=str(uuid.uuid4()),
        task_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        worker_id="worker",
        lease_id=str(uuid.uuid4()),
    )
    result = registry.invoke(
        ToolInvocation(
            action="decision.recommend_next_action",
            input={
                "goal": "Advance opportunity",
                "options": [
                    {"option_id": "draft_followup", "label": "Draft follow-up"},
                    {"option_id": "wait", "label": "Wait"},
                ],
                "criteria": [{"criterion_id": "fit", "label": "Fit", "weight": 1.0}],
                "evidence": [
                    {
                        "evidence_id": "e1",
                        "claim": "Strong ICP match on Acme",
                        "status": "known",
                        "confidence": 0.95,
                        "supports_option_ids": ["draft_followup"],
                        "supports_criterion_ids": ["fit"],
                        "about_object_refs": [
                            {"object_type": "opportunity", "object_id": "opp-1"},
                            {"object_type": "account", "object_id": "acct-acme"},
                        ],
                    }
                ],
            },
        ),
        context,
    )
    assert result.output["recommendation"] == "draft_followup"
    assert result.action == "decision.recommend_next_action"
