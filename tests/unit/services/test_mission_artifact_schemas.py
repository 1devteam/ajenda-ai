from backend.services.mission_composition.artifact_schemas import (
    ARTIFACT_SCHEMAS_BY_KEY,
    OBSERVED_CONTACTS_SCHEMA,
    PROSPECT_CANDIDATES_SCHEMA,
    QUALIFIED_PROSPECTS_SCHEMA,
    validate_artifact_payload,
    validate_artifact_schema_catalog,
)


def test_prospect_candidates_schema_exposes_explicit_research_fields() -> None:
    schema = PROSPECT_CANDIDATES_SCHEMA

    assert schema.artifact_key == "prospect_candidates"
    assert schema.producer_job == "research.discover_prospects"
    assert [field.deliverable_field for field in schema.fields] == [
        "website",
        "product_description",
        "research_summary",
        "sources",
    ]
    assert [field.json_path for field in schema.fields] == [
        "$[].website",
        "$[].product_description",
        "$[].research_summary",
        "$[].sources",
    ]
    assert all(field.scope == "per_item" for field in schema.fields)
    assert all(field.required_when_item_exists for field in schema.fields)
    assert schema.grants_execution_authority is False


def test_observed_contacts_schema_preserves_source_lineage() -> None:
    schema = OBSERVED_CONTACTS_SCHEMA

    assert schema.artifact_key == "observed_contacts"
    assert schema.producer_job == "research.observe_sources"
    assert [field.deliverable_field for field in schema.fields] == ["sources"]
    assert [field.json_path for field in schema.fields] == ["$[].sources"]
    assert schema.grants_execution_authority is False


def test_qualified_prospects_schema_exposes_qualification_deliverable_fields() -> None:
    schema = QUALIFIED_PROSPECTS_SCHEMA

    assert schema.artifact_key == "qualified_prospects"
    assert schema.producer_job == "sales.qualify_prospects"
    assert [field.deliverable_field for field in schema.fields] == [
        "company_name",
        "qualification_score",
        "qualification_reasons",
        "qualification_evidence",
        "ajenda_relevance",
    ]
    assert [field.json_path for field in schema.fields] == [
        "$[].company",
        "$[].score",
        "$[].reasons",
        "$[].qualification_evidence",
        "$[].ajenda_relevance",
    ]
    assert all(field.scope == "per_item" for field in schema.fields)
    assert all(field.required_when_item_exists for field in schema.fields)
    assert schema.grants_execution_authority is False


def test_artifact_schema_catalog_matches_job_outputs() -> None:
    validate_artifact_schema_catalog()

    assert tuple(ARTIFACT_SCHEMAS_BY_KEY) == (
        "prospect_candidates",
        "observed_contacts",
        "qualified_prospects",
        "revenue_records",
    )


def test_artifact_payload_validation_rejects_empty_per_item_lists() -> None:
    assert validate_artifact_payload(PROSPECT_CANDIDATES_SCHEMA, []) == (
        "typed per-item artifact payload must contain at least one item",
    )


def test_artifact_payload_validation_accepts_structurally_complete_rows() -> None:
    assert (
        validate_artifact_payload(
            PROSPECT_CANDIDATES_SCHEMA,
            [
                {
                    "website": "https://acme.example",
                    "product_description": "",
                    "research_summary": "Acme was identified in a public result.",
                    "sources": ["https://acme.example"],
                }
            ],
        )
        == ()
    )


def test_artifact_payload_validation_reports_all_structural_errors() -> None:
    assert validate_artifact_payload(PROSPECT_CANDIDATES_SCHEMA, {"website": "https://acme.example"}) == (
        "typed per-item artifact payload must be a list",
    )
    assert validate_artifact_payload(
        PROSPECT_CANDIDATES_SCHEMA,
        [
            "not-an-object",
            {
                "website": "https://acme.example",
                "product_description": None,
            },
        ],
    ) == (
        "item 0 must be an object",
        "item 1 missing required field: product_description",
        "item 1 missing required field: research_summary",
        "item 1 missing required field: sources",
    )
