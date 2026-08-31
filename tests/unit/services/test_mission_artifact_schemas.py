from backend.services.mission_composition.artifact_schemas import (
    ARTIFACT_SCHEMAS_BY_KEY,
    QUALIFIED_PROSPECTS_SCHEMA,
    validate_artifact_schema_catalog,
)


def test_qualified_prospects_schema_exposes_only_guaranteed_deliverable_fields() -> None:
    schema = QUALIFIED_PROSPECTS_SCHEMA

    assert schema.artifact_key == "qualified_prospects"
    assert schema.producer_job == "sales.qualify_prospects"
    assert [field.deliverable_field for field in schema.fields] == [
        "company_name",
        "qualification_score",
        "qualification_reasons",
    ]
    assert [field.json_path for field in schema.fields] == [
        "$[].company",
        "$[].score",
        "$[].reasons",
    ]
    assert all(field.scope == "per_item" for field in schema.fields)
    assert all(field.required_when_item_exists for field in schema.fields)
    assert schema.grants_execution_authority is False


def test_artifact_schema_catalog_matches_job_outputs() -> None:
    validate_artifact_schema_catalog()

    assert tuple(ARTIFACT_SCHEMAS_BY_KEY) == ("qualified_prospects",)
