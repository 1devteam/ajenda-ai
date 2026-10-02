from __future__ import annotations

from backend.services.mission_composition.semantic_vocabulary import (
    ALL_SEMANTIC_CONCEPTS,
    SHARED_BUSINESS_CONCEPTS,
    build_semantic_selection,
    resolve_shared_concept,
)


def test_shared_vocabulary_resolves_canonical_ids_and_aliases() -> None:
    assert resolve_shared_concept("prospect").concept_id == "prospect"
    assert resolve_shared_concept("  target account ").concept_id == "prospect"
    assert resolve_shared_concept("follow-up").concept_id == "outreach"


def test_shared_vocabulary_keeps_unknown_terms_unresolved() -> None:
    assert resolve_shared_concept("unmapped business signal") is None


def test_domain_and_industry_overlays_resolve_without_runtime_authority() -> None:
    assert resolve_shared_concept("heat pump").concept_id == "heat_pump"
    assert resolve_shared_concept("storm damage").concept_id == "storm_damage"
    assert resolve_shared_concept("job candidate").concept_id == "candidate"
    assert resolve_shared_concept("SKU").concept_id == "sku"


def test_shared_vocabulary_is_versioned_and_non_authoritative() -> None:
    assert len(SHARED_BUSINESS_CONCEPTS) >= 7
    assert all(concept.version == "1.0.0" for concept in SHARED_BUSINESS_CONCEPTS)
    assert all(concept.grants_execution_authority is False for concept in SHARED_BUSINESS_CONCEPTS)
    assert all(concept.version == "1.0.0" for concept in ALL_SEMANTIC_CONCEPTS)
    assert all(concept.grants_execution_authority is False for concept in ALL_SEMANTIC_CONCEPTS)


def test_semantic_selection_records_outcome_to_job_provenance() -> None:
    selection = build_semantic_selection(
        instruction="Research prospects, qualify them, and prepare outreach drafts.",
        requested_outcomes=("research_prospects", "qualify_prospects", "prepare_outreach"),
        selected_job_keys=(
            "research.discover_prospects",
            "sales.qualify_prospects",
            "email.prepare_outreach",
        ),
    )

    assert selection.concepts == ("prospect", "qualification", "outreach")
    assert {binding.status for binding in selection.bindings} == {"satisfied"}
    assert selection.conflicts == ()
    assert selection.grants_execution_authority is False


def test_semantic_selection_exposes_industry_overlay_terms() -> None:
    selection = build_semantic_selection(
        instruction="Research HVAC companies offering heat pump maintenance plans in Dallas.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )

    assert {"prospect", "heat_pump", "maintenance_plan"}.issubset(selection.concepts)
    assert {"heat pump", "maintenance plans"}.issubset(selection.matched_terms)
    assert selection.lattice_version == "1.0.0"
    assert selection.active_components == (
        "shared_business",
        "gtm.core",
        "local_service_business",
        "field_service",
        "recurring_service_business",
        "hvac",
    )
    assert selection.conflicts == ()
    assert selection.grants_execution_authority is False


def test_advertising_overlay_is_declarative_and_catalog_only() -> None:
    selection = build_semantic_selection(
        instruction="Analyze paid media campaigns, target audience, ad creative, ad spend, impressions, clicks, and conversions.",
        requested_outcomes=(),
        selected_job_keys=(),
    )

    assert {"campaign", "audience", "creative", "ad_budget", "impression", "click", "ad_conversion"}.issubset(
        selection.concepts
    )
    assert "advertising" in selection.active_components
    assert selection.active_components[:3] == ("shared_business", "gtm.core", "advertising")
    assert selection.grants_execution_authority is False


def test_multi_parent_overlay_inherits_all_required_domains() -> None:
    dental = build_semantic_selection(
        instruction="Research dental patients and appointments in Austin.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )
    recruiting = build_semantic_selection(
        instruction="Research recruiting candidates for a software employer.",
        requested_outcomes=("research_prospects",),
        selected_job_keys=("research.discover_prospects",),
    )

    assert {"shared_business", "gtm.core", "healthcare_business", "local_service_business", "dental"}.issubset(
        dental.active_components
    )
    assert {"shared_business", "gtm.core", "professional_services", "b2b_sales", "recruiting"}.issubset(
        recruiting.active_components
    )
    assert dental.component_conflicts == ()
    assert recruiting.component_conflicts == ()


def test_semantic_selection_fails_closed_when_a_required_job_is_missing() -> None:
    selection = build_semantic_selection(
        instruction="Qualify the prospects.",
        requested_outcomes=("qualify_prospects",),
        selected_job_keys=(),
    )

    assert selection.conflicts
    assert selection.bindings[0].status == "conflict"
