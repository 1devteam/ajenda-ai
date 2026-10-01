from __future__ import annotations

from backend.services.mission_composition.semantic_vocabulary import (
    SHARED_BUSINESS_CONCEPTS,
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
