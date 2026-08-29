from backend.services.mission_composition.deliverable_completion import (
    MaterializedArtifact,
    evaluate_deliverable_completion,
    validate_materialized_artifact,
)
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_projection import project_deliverable_request


def _projection(text: str):
    request = extract_deliverable_request(text)
    assert request is not None
    return project_deliverable_request(request)


def _qualified_row() -> dict[str, object]:
    return {
        "company": "Acme HVAC",
        "score": 84,
        "reasons": ["five employees verified", "Phoenix HVAC fit"],
        "qualification_evidence": {
            "qualification_dimensions": {"business_fit": 10},
            "qualification_reasons": ["five employees verified", "Phoenix HVAC fit"],
            "source_references": ["https://acme.example"],
        },
        "ajenda_relevance": "Ajenda may be relevant to the observed estimate follow-up workflow.",
    }


def test_typed_and_whole_artifact_fields_complete_only_after_materialization() -> None:
    projection = _projection("Return company name, qualification reasons, qualification score, and drafts.")

    before = evaluate_deliverable_completion(projection, [])
    assert before.complete is False
    assert {field.field_key: field.status for field in before.fields} == {
        "company_name": "missing_artifact",
        "qualification_reasons": "missing_artifact",
        "qualification_score": "missing_artifact",
        "drafts": "missing_artifact",
    }

    after = evaluate_deliverable_completion(
        projection,
        [
            MaterializedArtifact(
                artifact_key="qualified_prospects",
                payload=[_qualified_row()],
            ),
            MaterializedArtifact(
                artifact_key="introduction_drafts",
                payload=[{"company": "Acme HVAC", "draft": "Hello Acme HVAC"}],
            ),
        ],
    )

    assert after.complete is True
    assert all(field.status == "satisfied" for field in after.fields)
    assert after.grants_execution_authority is False


def test_invalid_typed_artifact_does_not_satisfy_bound_field() -> None:
    projection = _projection("Return company name and qualification reasons.")
    artifact = MaterializedArtifact(
        artifact_key="qualified_prospects",
        payload=[
            {
                "company": "Acme HVAC",
                "score": 84,
                "qualification_evidence": {"qualification_dimensions": {"business_fit": 10}},
                "ajenda_relevance": "Ajenda may be relevant to an observed workflow.",
            }
        ],
    )

    validation = validate_materialized_artifact(artifact)
    completion = evaluate_deliverable_completion(projection, [artifact])
    by_field = {field.field_key: field.status for field in completion.fields}

    assert validation.schema_known is True
    assert validation.valid is False
    assert validation.errors == ("item 0 missing required field: reasons",)
    assert by_field["company_name"] == "invalid_artifact"
    assert by_field["qualification_reasons"] == "invalid_artifact"
    assert completion.complete is False


def test_bound_fields_remain_incomplete_when_required_artifacts_are_missing() -> None:
    projection = _projection("Return research, qualification reasons, sources, drafts, assumptions, and limitations.")
    completion = evaluate_deliverable_completion(
        projection,
        [
            MaterializedArtifact(
                artifact_key="qualified_prospects",
                payload=[_qualified_row()],
            ),
            MaterializedArtifact(
                artifact_key="introduction_drafts",
                payload=[{"draft": "Hello Acme HVAC"}],
            ),
        ],
    )
    by_field = {field.field_key: field.status for field in completion.fields}

    assert by_field["qualification_reasons"] == "satisfied"
    assert by_field["drafts"] == "satisfied"
    assert by_field["research_summary"] == "missing_artifact"
    assert by_field["sources"] == "missing_artifact"
    assert by_field["assumptions"] == "unproven"
    assert by_field["limitations"] == "unproven"
    assert completion.complete is False


def test_remaining_revops_fields_require_valid_materialized_values() -> None:
    projection = _projection(
        "Return the website, product description, qualification evidence, "
        "Ajenda relevance, research summary, and sources."
    )
    completion = evaluate_deliverable_completion(
        projection,
        [
            MaterializedArtifact(
                artifact_key="prospect_candidates",
                payload=[
                    {
                        "website": "https://acme.example",
                        "product_description": "Residential HVAC installation and service.",
                        "research_summary": "Acme serves residential customers in Phoenix.",
                        "sources": ["https://acme.example"],
                    }
                ],
            ),
            MaterializedArtifact(
                artifact_key="observed_contacts",
                payload=[{"sources": ["https://acme.example/contact"]}],
            ),
            MaterializedArtifact(
                artifact_key="qualified_prospects",
                payload=[_qualified_row()],
            ),
        ],
    )

    assert completion.complete is True
    assert all(field.status == "satisfied" for field in completion.fields)
    assert completion.grants_execution_authority is False


def test_empty_explicit_field_remains_incomplete_without_invalidating_artifact_shape() -> None:
    projection = _projection("Return product description.")
    artifact = MaterializedArtifact(
        artifact_key="prospect_candidates",
        payload=[
            {
                "website": "https://acme.example",
                "product_description": "",
                "research_summary": "A public result identified Acme.",
                "sources": ["https://acme.example"],
            }
        ],
    )

    validation = validate_materialized_artifact(artifact)
    completion = evaluate_deliverable_completion(projection, [artifact])

    assert validation.valid is True
    assert completion.fields[0].status == "invalid_artifact"
    assert completion.complete is False


def test_unknown_requested_item_keeps_completion_false() -> None:
    projection = _projection("Return company name and lunar risk index.")
    completion = evaluate_deliverable_completion(
        projection,
        [
            MaterializedArtifact(
                artifact_key="qualified_prospects",
                payload=[_qualified_row()],
            )
        ],
    )

    assert completion.fields[0].status == "satisfied"
    assert completion.unresolved_request_items == ("lunar risk index",)
    assert completion.complete is False
