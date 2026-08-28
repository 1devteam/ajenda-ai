"""Typed composition artifact schemas for deliverable projection.

Schemas describe the fields an artifact contract guarantees when that artifact is
materialized. They do not select jobs, validate runtime execution, grant authority,
or claim that an artifact has actually been produced.
"""

from __future__ import annotations

from typing import Literal

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
    ),
)

ARTIFACT_SCHEMAS_BY_KEY: dict[str, CompositionArtifactSchema] = {
    QUALIFIED_PROSPECTS_SCHEMA.artifact_key: QUALIFIED_PROSPECTS_SCHEMA,
}


def validate_artifact_schema_catalog() -> None:
    """Fail closed if a schema drifts away from the declared job output vocabulary."""

    for artifact_key, schema in ARTIFACT_SCHEMAS_BY_KEY.items():
        if artifact_key != schema.artifact_key:
            raise ValueError(f"artifact schema key mismatch: {artifact_key}")
        job = BUSINESS_JOBS_BY_KEY.get(schema.producer_job)
        if job is None:
            raise ValueError(f"artifact schema references unknown producer job: {schema.producer_job}")
        if schema.artifact_key not in set(job.produced_outputs):
            raise ValueError(
                f"artifact schema {schema.artifact_key} is not a declared output of {schema.producer_job}"
            )
        field_keys = [field.deliverable_field for field in schema.fields]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError(f"artifact schema contains duplicate deliverable fields: {schema.artifact_key}")
