from __future__ import annotations

from types import SimpleNamespace

from backend.services.mission_composition.semantic_vocabulary import (
    TenantSemanticOverride,
    build_semantic_selection,
    resolve_shared_concept,
)
from backend.services.mission_composition.service import _tenant_semantic_overrides


def test_tenant_alias_guides_selection_without_mutating_shared_vocabulary() -> None:
    override = TenantSemanticOverride(
        concept_id="customer",
        aliases=("member",),
        source_reference="business_profile:tenant-1",
        version="1.0.0",
    )

    selection = build_semantic_selection(
        instruction="Research member companies in Austin.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
        tenant_overrides=(override,),
    )

    assert "customer" in selection.concepts
    assert "member" in selection.matched_terms
    assert selection.tenant_overrides == (override,)
    assert selection.grants_execution_authority is False
    assert resolve_shared_concept("member") is None


def test_tenant_alias_conflict_fails_closed_against_shared_alias() -> None:
    override = TenantSemanticOverride(
        concept_id="customer",
        aliases=("lead",),
        source_reference="business_profile:tenant-1",
        version="1.0.0",
    )

    selection = build_semantic_selection(
        instruction="Research lead companies in Austin.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
        tenant_overrides=(override,),
    )

    assert any("tenant semantic alias conflict" in conflict for conflict in selection.conflicts)
    assert "customer" not in selection.concepts


def test_profile_override_parser_is_tenant_private_and_reports_invalid_entries() -> None:
    profile = SimpleNamespace(
        id="profile-1",
        approved_facts={
            "semantic_terminology_overrides": [
                {"concept_id": "prospect", "aliases": ["account target"]},
                {"concept_id": "missing", "aliases": ["unknown"]},
                "malformed",
            ]
        },
    )

    overrides, conflicts = _tenant_semantic_overrides(profile)

    assert len(overrides) == 2
    assert overrides[0].scope == "tenant_private"
    assert overrides[0].source_reference == "business_profile:profile-1"
    assert any("must be an object" in conflict for conflict in conflicts)
