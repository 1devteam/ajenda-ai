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
                payload=[
                    {
                        "company": "Acme HVAC",
                        "score": 84,
                        "reasons": ["five employees verified", "Phoenix HVAC fit"],
                    }
                ],
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
        payload=[{"company": "Acme HVAC", "score": 84}],
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


def test_candidate_and_unresolved_fields_remain_incomplete_even_when_jobs_could_complete() -> None:
    projection = _projection("Return research, qualification reasons, sources, drafts, assumptions, and limitations.")
    completion = evaluate_deliverable_completion(
        projection,
        [
            MaterializedArtifact(
                artifact_key="qualified_prospects",
                payload=[{"company": "Acme HVAC", "score": 84, "reasons": ["fit"]}],
            ),
            MaterializedArtifact(
                artifact_key="introduction_drafts",
                payload=[{"draft": "Hello Acme HVAC"}],
            ),
            MaterializedArtifact(
                artifact_key="researched_prospects",
                payload=[{"company": "Acme HVAC", "summary": "research exists"}],
            ),
        ],
    )
    by_field = {field.field_key: field.status for field in completion.fields}

    assert by_field["qualification_reasons"] == "satisfied"
    assert by_field["drafts"] == "satisfied"
    assert by_field["research_summary"] == "unproven"
    assert by_field["sources"] == "unproven"
    assert by_field["assumptions"] == "unproven"
    assert by_field["limitations"] == "unproven"
    assert completion.complete is False


def test_unknown_requested_item_keeps_completion_false() -> None:
    projection = _projection("Return company name and lunar risk index.")
    completion = evaluate_deliverable_completion(
        projection,
        [
            MaterializedArtifact(
                artifact_key="qualified_prospects",
                payload=[{"company": "Acme HVAC", "score": 84, "reasons": ["fit"]}],
            )
        ],
    )

    assert completion.fields[0].status == "satisfied"
    assert completion.unresolved_request_items == ("lunar risk index",)
    assert completion.complete is False
