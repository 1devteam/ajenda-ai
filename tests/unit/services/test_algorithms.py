import pytest

from backend.services.ontology.algorithms import (
    ALGORITHM_REGISTRY,
    AlgorithmResult,
    evaluate_business_identity_verification,
    evaluate_composition_algorithms,
    evaluate_duplicate_identity_resolution,
    evaluate_lead_fit_score,
    evaluate_runtime_artifact_completeness,
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


def test_business_identity_verification_requires_two_source_backed_observations() -> None:
    insufficient = evaluate_business_identity_verification(
        [{"name": "Acme HVAC", "domain": "acme.example", "evidence_ref": "page:one"}]
    )
    verified = evaluate_business_identity_verification(
        [
            {"name": "Acme HVAC", "domain": "acme.example", "evidence_ref": "page:one"},
            {"name": "ACME HVAC", "domain": "acme.example", "evidence_ref": "registry:one"},
        ]
    )

    assert insufficient.status == "insufficient_evidence"
    assert insufficient.output["verified"] is False
    assert verified.status == "evaluated"
    assert verified.output["verified"] is True
    assert verified.evidence_refs == ("page:one", "registry:one")


def test_business_identity_verification_reports_source_backed_conflicts() -> None:
    result = evaluate_business_identity_verification(
        [
            {"name": "Acme HVAC", "domain": "acme.example", "evidence_ref": "page:one"},
            {"name": "Other HVAC", "domain": "other.example", "evidence_ref": "registry:one"},
        ]
    )

    assert result.status == "conflict"
    assert result.output["verified"] is False
    assert set(result.output["conflicting_fields"]) == {"name", "domain"}


def test_lead_fit_uses_only_explicit_source_backed_signals() -> None:
    result = evaluate_lead_fit_score(
        signals={"industry_match": True, "service_area_match": False, "budget_confirmed": True},
        evidence_refs_by_signal={"industry_match": "candidate:industry", "service_area_match": "candidate:location"},
        weights={"industry_match": 2.0, "service_area_match": 1.0, "budget_confirmed": 3.0},
    )

    assert result.status == "evaluated"
    assert result.output["lead_fit_score"] == pytest.approx(66.67)
    assert result.output["evidence_coverage"] == pytest.approx(0.5)
    assert result.output["unknown_signals"] == ["budget_confirmed"]
    assert result.evidence_refs == ("candidate:industry", "candidate:location")


def test_service_area_algorithm_fails_closed_without_inputs() -> None:
    result = evaluate_service_area_match(target_location=None, service_areas=[])
    assert result.status == "insufficient_evidence"
    assert result.output["matched"] is None
    assert result.grants_execution_authority is False


def test_runtime_artifact_completeness_does_not_inherit_composition_success() -> None:
    result = evaluate_runtime_artifact_completeness(
        task_count=3,
        failed_task_count=0,
        acceptance_met=False,
        acceptance_reasons=["required 5 verified prospect identities, produced 3"],
        materialized_artifact_keys=["observed_contacts"],
    )
    assert result.output["evaluation_phase"] == "runtime"
    assert result.output["completeness_score"] == 0.0
    assert result.provenance["algorithm_id"] == "gtm.runtime_artifact_completeness.v1"
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
