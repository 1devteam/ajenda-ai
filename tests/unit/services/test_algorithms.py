import pytest

from backend.services.ontology.algorithms import (
    ALGORITHM_REGISTRY,
    AlgorithmResult,
    evaluate_composition_algorithms,
    evaluate_duplicate_identity_resolution,
    evaluate_service_area_match,
    validate_composition_algorithm_results,
)


def test_algorithm_registry_is_unique_and_non_authoritative() -> None:
    ids = [item.algorithm_id for item in ALGORITHM_REGISTRY]
    assert len(ids) == len(set(ids))
    assert all(item.grants_execution_authority is False for item in ALGORITHM_REGISTRY)


def test_composition_algorithms_are_deterministic_and_provenanced() -> None:
    kwargs = {
        "requested_outcomes": ["research_prospects"],
        "named_jobs": ["research.discover_prospects"],
        "planned_steps": ["step-1"],
        "interpretation_evidence": [{"field_path": "target_entities", "confidence": 0.9}],
        "blocking_gap_count": 0,
    }
    first = evaluate_composition_algorithms(**kwargs)
    second = evaluate_composition_algorithms(**kwargs)
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]
    assert all(item.input_sha256 for item in first)
    assert all(item.grants_execution_authority is False for item in first)
    assert first[0].output["completeness_score"] == 1.0


def test_duplicate_identity_algorithm_groups_stable_identifiers() -> None:
    result = evaluate_duplicate_identity_resolution(
        [{"id": "a", "email": "same@example.com"}, {"id": "b", "email": "same@example.com"}]
    )
    assert result.output["duplicate_groups"] == [["a", "b"]]
    assert result.confidence == 1.0


def test_service_area_algorithm_fails_closed_without_inputs() -> None:
    result = evaluate_service_area_match(target_location=None, service_areas=[])
    assert result.status == "insufficient_evidence"
    assert result.output["matched"] is None
    assert result.grants_execution_authority is False


def test_algorithm_result_rejects_unknown_or_mismatched_provenance() -> None:
    with pytest.raises(ValueError, match="unknown algorithm"):
        AlgorithmResult(
            algorithm_id="unknown.v1",
            version="1",
            status="evaluated",
            confidence=1.0,
            input_sha256="0" * 64,
        )
    result = evaluate_composition_algorithms(
        requested_outcomes=["research_prospects"],
        named_jobs=["research.discover_prospects"],
        planned_steps=["step-1"],
        interpretation_evidence=[{"field_path": "target", "confidence": 1.0}],
        blocking_gap_count=0,
    )
    tampered = result[0].model_copy(update={"input_sha256": "f" * 64})
    with pytest.raises(ValueError, match="stale or inconsistent"):
        validate_composition_algorithm_results(
            results=(tampered, result[1]),
            requested_outcomes=["research_prospects"],
            named_jobs=["research.discover_prospects"],
            planned_steps=["step-1"],
            interpretation_evidence=[{"field_path": "target", "confidence": 1.0}],
            blocking_gap_count=0,
        )
