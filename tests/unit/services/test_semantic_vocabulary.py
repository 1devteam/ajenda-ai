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
    assert selection.conflicts == ()
    assert selection.grants_execution_authority is False


def test_semantic_selection_fails_closed_when_a_required_job_is_missing() -> None:
    selection = build_semantic_selection(
        instruction="Qualify the prospects.",
        requested_outcomes=("qualify_prospects",),
        selected_job_keys=(),
    )

    assert selection.conflicts
    assert selection.bindings[0].status == "conflict"
