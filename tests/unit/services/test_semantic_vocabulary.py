from __future__ import annotations

from backend.services.mission_composition.semantic_vocabulary import (
    SHARED_BUSINESS_CONCEPTS,
    build_semantic_selection,
    resolve_shared_concept,
)


def test_shared_vocabulary_resolves_canonical_ids_and_aliases() -> None:
    assert resolve_shared_concept("prospect").concept_id == "prospect"
    assert resolve_shared_concept("  target account ").concept_id == "prospect"
    assert resolve_shared_concept("follow-up").concept_id == "outreach"


def test_shared_vocabulary_keeps_unknown_terms_unresolved() -> None:
    assert resolve_shared_concept("heat pump") is None


def test_shared_vocabulary_is_versioned_and_non_authoritative() -> None:
    assert len(SHARED_BUSINESS_CONCEPTS) >= 7
    assert all(concept.version == "1.0.0" for concept in SHARED_BUSINESS_CONCEPTS)
    assert all(concept.grants_execution_authority is False for concept in SHARED_BUSINESS_CONCEPTS)


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


def test_semantic_selection_fails_closed_when_a_required_job_is_missing() -> None:
    selection = build_semantic_selection(
        instruction="Qualify the prospects.",
        requested_outcomes=("qualify_prospects",),
        selected_job_keys=(),
    )

    assert selection.conflicts
    assert selection.bindings[0].status == "conflict"
