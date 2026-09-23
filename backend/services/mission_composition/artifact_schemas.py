"""Typed composition artifact schemas and structural payload validation.

Schemas describe the fields an artifact contract guarantees when that artifact is
materialized. The shared validator is used by runtime completion and the descriptive
deliverable read model. Schemas do not select jobs, grant execution authority, or
claim that an artifact has actually been produced.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY


class ArtifactFieldProjection(BaseModel):
    """One guaranteed projection from an artifact into a deliverable field."""

    model_config = ConfigDict(extra="forbid")

    deliverable_field: DeliverableFieldKey
    json_path: str = Field(min_length=1, max_length=240)
    scope: Literal["per_item", "whole_artifact"]
    required_when_item_exists: bool = True


class CompositionArtifactSchema(BaseModel):
    """Declarative field contract for one composition artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    artifact_key: str = Field(min_length=1, max_length=120)
    producer_job: str = Field(min_length=1, max_length=160)
    fields: tuple[ArtifactFieldProjection, ...] = Field(min_length=1, max_length=30)
    grants_execution_authority: Literal[False] = False


PROSPECT_CANDIDATES_SCHEMA = CompositionArtifactSchema(
    artifact_key="prospect_candidates",
    producer_job="research.discover_prospects",
    fields=(
        ArtifactFieldProjection(
            deliverable_field="website",
            json_path="$[].website",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="product_description",
            json_path="$[].product_description",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="research_summary",
            json_path="$[].research_summary",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="sources",
            json_path="$[].sources",
            scope="per_item",
        ),
    ),
)

OBSERVED_CONTACTS_SCHEMA = CompositionArtifactSchema(
    artifact_key="observed_contacts",
    producer_job="research.observe_sources",
    fields=(
        ArtifactFieldProjection(
            deliverable_field="sources",
            json_path="$[].sources",
            scope="per_item",
        ),
    ),
)

VERIFIED_PROSPECT_CANDIDATES_SCHEMA = CompositionArtifactSchema(
    artifact_key="verified_prospect_candidates",
    producer_job="research.observe_sources",
    fields=(
        ArtifactFieldProjection(deliverable_field="website", json_path="$[].website", scope="per_item"),
        ArtifactFieldProjection(
            deliverable_field="product_description", json_path="$[].product_description", scope="per_item"
        ),
        ArtifactFieldProjection(
            deliverable_field="research_summary", json_path="$[].research_summary", scope="per_item"
        ),
        ArtifactFieldProjection(deliverable_field="sources", json_path="$[].sources", scope="per_item"),
    ),
)

PUBLIC_IDENTITY_OBSERVATION_SCHEMA = CompositionArtifactSchema(
    artifact_key="public_identity_observation",
    producer_job="research.verify_public_identity",
    fields=(
        ArtifactFieldProjection(
            deliverable_field="expected_company", json_path="$.expected_company", scope="whole_artifact"
        ),
        ArtifactFieldProjection(
            deliverable_field="expected_industry", json_path="$.expected_industry", scope="whole_artifact"
        ),
        ArtifactFieldProjection(
            deliverable_field="expected_location", json_path="$.expected_location", scope="whole_artifact"
        ),
        ArtifactFieldProjection(
            deliverable_field="identity_status", json_path="$.identity_status", scope="whole_artifact"
        ),
        ArtifactFieldProjection(
            deliverable_field="identity_evidence_urls", json_path="$.identity_evidence_urls", scope="whole_artifact"
        ),
        ArtifactFieldProjection(
            deliverable_field="identity_match_reasons", json_path="$.identity_match_reasons", scope="whole_artifact"
        ),
        ArtifactFieldProjection(deliverable_field="identity_gaps", json_path="$.identity_gaps", scope="whole_artifact"),
        ArtifactFieldProjection(deliverable_field="source_url", json_path="$.source_url", scope="whole_artifact"),
    ),
)

QUALIFIED_PROSPECTS_SCHEMA = CompositionArtifactSchema(
    artifact_key="qualified_prospects",
    producer_job="sales.qualify_prospects",
    fields=(
        ArtifactFieldProjection(
            deliverable_field="company_name",
            json_path="$[].company",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="qualification_score",
            json_path="$[].score",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="qualification_reasons",
            json_path="$[].reasons",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="qualification_evidence",
            json_path="$[].qualification_evidence",
            scope="per_item",
        ),
        ArtifactFieldProjection(
            deliverable_field="ajenda_relevance",
            json_path="$[].ajenda_relevance",
            scope="per_item",
        ),
    ),
)

REVENUE_RECORDS_SCHEMA = CompositionArtifactSchema(
    artifact_key="revenue_records",
    producer_job="accounting.read_revenue",
    fields=(
        ArtifactFieldProjection(deliverable_field="revenue_amount", json_path="$[].amount", scope="per_item"),
        ArtifactFieldProjection(deliverable_field="revenue_currency", json_path="$[].currency", scope="per_item"),
        ArtifactFieldProjection(deliverable_field="revenue_source", json_path="$[].source", scope="per_item"),
    ),
)

BUSINESS_REVIEW_REPORT_SCHEMA = CompositionArtifactSchema(
    artifact_key="business_review_report",
    producer_job="business.review_income",
    fields=(
        ArtifactFieldProjection(
            deliverable_field="research_summary",
            json_path="$.income_opportunities",
            scope="whole_artifact",
        ),
        ArtifactFieldProjection(
            deliverable_field="assumptions",
            json_path="$.assumptions",
            scope="whole_artifact",
        ),
        ArtifactFieldProjection(
            deliverable_field="limitations",
            json_path="$.evidence_gaps",
            scope="whole_artifact",
        ),
    ),
)

WEB_PAGE_OBSERVATION_SCHEMA = CompositionArtifactSchema(
    artifact_key="web_page_observation",
    producer_job="research.observe_web_page",
    fields=(
        ArtifactFieldProjection(deliverable_field="source_url", json_path="$.source_url", scope="whole_artifact"),
        ArtifactFieldProjection(deliverable_field="final_url", json_path="$.final_url", scope="whole_artifact"),
        ArtifactFieldProjection(deliverable_field="title", json_path="$.title", scope="whole_artifact"),
        ArtifactFieldProjection(
            deliverable_field="extracted_observations",
            json_path="$.extracted_observations",
            scope="whole_artifact",
        ),
        ArtifactFieldProjection(
            deliverable_field="observation_timestamp",
            json_path="$.observation_timestamp",
            scope="whole_artifact",
        ),
        ArtifactFieldProjection(deliverable_field="browser_trace", json_path="$.browser_trace", scope="whole_artifact"),
        ArtifactFieldProjection(
            deliverable_field="blocked_requests", json_path="$.blocked_requests", scope="whole_artifact"
        ),
        ArtifactFieldProjection(
            deliverable_field="observation_satisfied",
            json_path="$.observation_satisfied",
            scope="whole_artifact",
        ),
    ),
)

ARTIFACT_SCHEMAS_BY_KEY: dict[str, CompositionArtifactSchema] = {
    PROSPECT_CANDIDATES_SCHEMA.artifact_key: PROSPECT_CANDIDATES_SCHEMA,
    OBSERVED_CONTACTS_SCHEMA.artifact_key: OBSERVED_CONTACTS_SCHEMA,
    VERIFIED_PROSPECT_CANDIDATES_SCHEMA.artifact_key: VERIFIED_PROSPECT_CANDIDATES_SCHEMA,
    PUBLIC_IDENTITY_OBSERVATION_SCHEMA.artifact_key: PUBLIC_IDENTITY_OBSERVATION_SCHEMA,
    QUALIFIED_PROSPECTS_SCHEMA.artifact_key: QUALIFIED_PROSPECTS_SCHEMA,
    REVENUE_RECORDS_SCHEMA.artifact_key: REVENUE_RECORDS_SCHEMA,
    BUSINESS_REVIEW_REPORT_SCHEMA.artifact_key: BUSINESS_REVIEW_REPORT_SCHEMA,
    WEB_PAGE_OBSERVATION_SCHEMA.artifact_key: WEB_PAGE_OBSERVATION_SCHEMA,
}


def _path_field(json_path: str) -> str | None:
    prefix = "$[]."
    if not json_path.startswith(prefix):
        return None
    field = json_path[len(prefix) :].strip()
    return field or None


def _public_prospect_errors(item: dict[str, Any], index: int) -> list[str]:
    """Enforce identity quality for rows sourced from public search.

    A provider returning a directory page is useful evidence, but it is not a
    company identity and must never count as a completed prospect artifact.
    """

    if item.get("source") != "public_search":
        return []
    errors: list[str] = []
    if item.get("real") is not True:
        errors.append(f"item {index} public prospect identity is not verified")
    if item.get("identity_status") != "verified":
        errors.append(f"item {index} public prospect identity_status must be verified")
    return errors


def validate_artifact_payload(schema: CompositionArtifactSchema, payload: Any) -> tuple[str, ...]:
    """Validate one emitted artifact payload against its declared structural schema."""

    errors: list[str] = []
    whole_fields = [field for field in schema.fields if field.scope == "whole_artifact"]
    if whole_fields:
        if not isinstance(payload, dict):
            return ("typed whole-artifact payload must be an object",)
        if schema.artifact_key == "web_page_observation" and payload.get("observation_satisfied") is not True:
            errors.append("web page observation requirements were not satisfied")
        for field in whole_fields:
            if not field.json_path.startswith("$."):
                errors.append(f"unsupported artifact schema path: {field.json_path}")
                continue
            path_field = field.json_path[2:].strip()
            if not path_field:
                errors.append(f"unsupported artifact schema path: {field.json_path}")
                continue
            if field.required_when_item_exists and (
                path_field not in payload or payload[path_field] is None or payload[path_field] == ""
            ):
                errors.append(f"artifact missing required field: {path_field}")

    per_item_fields = [field for field in schema.fields if field.scope == "per_item"]
    if per_item_fields:
        if not isinstance(payload, list):
            return ("typed per-item artifact payload must be a list",)
        if not payload:
            return ("typed per-item artifact payload must contain at least one item",)
        for index, item in enumerate(payload):
            if not isinstance(item, dict):
                errors.append(f"item {index} must be an object")
                continue
            errors.extend(_public_prospect_errors(item, index))
            if schema.artifact_key == "verified_prospect_candidates" and not str(item.get("company") or "").strip():
                errors.append(f"item {index} missing required field: company")
            for field in per_item_fields:
                item_path_field = _path_field(field.json_path)
                if item_path_field is None:
                    errors.append(f"unsupported artifact schema path: {field.json_path}")
                    continue
                if field.required_when_item_exists and (item_path_field not in item or item[item_path_field] is None):
                    errors.append(f"item {index} missing required field: {item_path_field}")
    return tuple(errors)


def validate_artifact_schema_catalog() -> None:
    """Fail closed if a schema drifts away from the declared job output vocabulary."""

    for artifact_key, schema in ARTIFACT_SCHEMAS_BY_KEY.items():
        if artifact_key != schema.artifact_key:
            raise ValueError(f"artifact schema key mismatch: {artifact_key}")
        job = BUSINESS_JOBS_BY_KEY.get(schema.producer_job)
        if job is None:
            raise ValueError(f"artifact schema references unknown producer job: {schema.producer_job}")
        if schema.artifact_key not in set(job.produced_outputs):
            raise ValueError(f"artifact schema {schema.artifact_key} is not a declared output of {schema.producer_job}")
        field_keys = [field.deliverable_field for field in schema.fields]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError(f"artifact schema contains duplicate deliverable fields: {schema.artifact_key}")
