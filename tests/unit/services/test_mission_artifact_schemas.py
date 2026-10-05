from backend.services.mission_composition.artifact_schemas import (
    ARTIFACT_SCHEMAS_BY_KEY,
    CRM_RECORDS_SCHEMA,
    ENRICHED_PROSPECTS_SCHEMA,
    INTERNAL_CRM_RECORDS_SCHEMA,
    INTRODUCTION_DRAFTS_SCHEMA,
    OBSERVED_CONTACTS_SCHEMA,
    PIPELINE_RECORDS_SCHEMA,
    PROSPECT_CANDIDATES_SCHEMA,
    QUALIFIED_PROSPECTS_SCHEMA,
    RESEARCHED_PROSPECTS_SCHEMA,
    WEB_PAGE_OBSERVATION_SCHEMA,
    validate_artifact_payload,
    validate_artifact_schema_catalog,
)


def test_prospect_candidates_schema_exposes_explicit_research_fields() -> None:
    schema = PROSPECT_CANDIDATES_SCHEMA

    assert schema.artifact_key == "prospect_candidates"
    assert schema.producer_job == "research.discover_prospects"
    assert [field.deliverable_field for field in schema.fields] == [
        "company_name",
        "website",
        "product_description",
        "research_summary",
        "sources",
        "research_source",
    ]
    assert [field.json_path for field in schema.fields] == [
        "$[].company",
        "$[].website",
        "$[].product_description",
        "$[].research_summary",
        "$[].sources",
        "$[].source",
    ]
    assert all(field.scope == "per_item" for field in schema.fields)
    assert all(
        field.required_when_item_exists
        for field in schema.fields
        if field.deliverable_field
        not in {
            "company_name",
            "qualification_dimensions",
            "disqualifiers",
            "recommended_next_action",
            "research_source",
        }
    )
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
        "website",
        "qualification_score",
        "qualification_reasons",
        "qualification_dimensions",
        "qualification_evidence",
        "supporting_evidence",
        "disqualifiers",
        "recommended_next_action",
        "ajenda_relevance",
    ]
    assert [field.json_path for field in schema.fields] == [
        "$[].company",
        "$[].website",
        "$[].score",
        "$[].reasons",
        "$[].qualification_dimensions",
        "$[].qualification_evidence",
        "$[].qualification_evidence",
        "$[].disqualifiers",
        "$[].recommended_next_action",
        "$[].ajenda_relevance",
    ]
    assert all(field.scope == "per_item" for field in schema.fields)
    assert all(
        field.required_when_item_exists
        for field in schema.fields
        if field.deliverable_field
        not in {"website", "qualification_dimensions", "disqualifiers", "recommended_next_action"}
    )
    assert schema.grants_execution_authority is False


def test_artifact_schema_catalog_matches_job_outputs() -> None:
    validate_artifact_schema_catalog()

    assert tuple(ARTIFACT_SCHEMAS_BY_KEY) == (
        "prospect_candidates",
        "observed_contacts",
        "verified_prospect_candidates",
        "public_identity_observation",
        "qualified_prospects",
        "revenue_records",
        "business_review_report",
        "web_page_observation",
        "goal_progress_evaluation",
        "researched_prospects",
        "enriched_prospects",
        "introduction_drafts",
        "internal_crm_records",
        "crm_records",
        "pipeline_records",
    )


def test_revops_stage_schemas_cover_internal_lane_outputs() -> None:
    assert (
        validate_artifact_payload(
            RESEARCHED_PROSPECTS_SCHEMA,
            [
                {
                    "crm_matches": [],
                    "research_notes": ["internal"],
                    "research_source": "ajenda_brain",
                    "research_real": True,
                }
            ],
        )
        == ()
    )
    assert (
        validate_artifact_payload(
            ENRICHED_PROSPECTS_SCHEMA,
            [{"company": "Acme", "contacts": [], "enrichment_mode": "unresolved", "enrichment_real": False}],
        )
        == ()
    )
    assert (
        validate_artifact_payload(
            INTRODUCTION_DRAFTS_SCHEMA,
            [{"artifact_id": "draft-1", "subject": "Hello", "recipient": None, "recipient_bound": False}],
        )
        == ()
    )
    assert (
        validate_artifact_payload(
            INTERNAL_CRM_RECORDS_SCHEMA,
            [{"id": "contact-1", "operation": "created"}],
        )
        == ()
    )
    assert (
        validate_artifact_payload(
            CRM_RECORDS_SCHEMA,
            [{"id": "contact-1", "source": "internal_record"}],
        )
        == ()
    )
    assert (
        validate_artifact_payload(
            PIPELINE_RECORDS_SCHEMA,
            [{"id": "opp-1", "status": "upserted", "source": "ajenda_brain", "data": {}}],
        )
        == ()
    )


def test_revops_artifact_validation_rejects_contradictory_or_non_real_rows() -> None:
    assert validate_artifact_payload(
        RESEARCHED_PROSPECTS_SCHEMA,
        [{"crm_matches": [], "research_notes": [], "research_source": "ajenda_brain", "research_real": False}],
    ) == ("item 0 research result is not marked real",)
    assert validate_artifact_payload(
        ENRICHED_PROSPECTS_SCHEMA,
        [{"company": "Acme", "contacts": [], "enrichment_mode": "local_simulated", "enrichment_real": True}],
    ) == ("item 0 simulated enrichment cannot be marked real", "item 0 enrichment mode contradicts enrichment_real")


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


def test_artifact_payload_rejects_unverified_public_prospect() -> None:
    errors = validate_artifact_payload(
        PROSPECT_CANDIDATES_SCHEMA,
        [
            {
                "website": "https://directory.example/hvac",
                "product_description": "",
                "research_summary": "A directory result.",
                "sources": ["https://directory.example/hvac"],
                "source": "public_search",
                "real": False,
                "identity_status": "unverified",
            }
        ],
    )
    assert errors == (
        "item 0 public prospect identity is not verified",
        "item 0 public prospect identity_status must be verified",
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


def test_web_page_observation_requires_typed_observation_fields() -> None:
    payload = {
        "source_url": "https://example.com",
        "final_url": "https://example.com/",
        "title": "Example Domain",
        "extracted_observations": [{"kind": "title", "satisfied": True}],
        "observation_timestamp": "2026-09-21T00:00:00Z",
        "browser_trace": [{"action": "navigate", "status_code": 200}],
        "blocked_requests": [],
        "observation_satisfied": True,
    }
    assert validate_artifact_payload(WEB_PAGE_OBSERVATION_SCHEMA, payload) == ()
    assert validate_artifact_payload(WEB_PAGE_OBSERVATION_SCHEMA, {"source_url": payload["source_url"]}) == (
        "web page observation requirements were not satisfied",
        "artifact missing required field: final_url",
        "artifact missing required field: title",
        "artifact missing required field: extracted_observations",
        "artifact missing required field: observation_timestamp",
        "artifact missing required field: browser_trace",
        "artifact missing required field: blocked_requests",
        "artifact missing required field: observation_satisfied",
    )
