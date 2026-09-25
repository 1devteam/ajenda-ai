"""Evaluate requested deliverables against materialized composition artifacts.

Completion is descriptive only. It does not complete tasks, select jobs, grant
authority, or materialize artifacts. A task may be completed while its requested
deliverable remains incomplete.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.services.mission_composition.artifact_schemas import (
    ARTIFACT_SCHEMAS_BY_KEY,
    validate_artifact_payload,
)
from backend.services.mission_composition.deliverable_contract import DeliverableFieldKey
from backend.services.mission_composition.deliverable_projection import DeliverableProjection

FieldCompletionStatus = Literal[
    "satisfied",
    "missing_artifact",
    "invalid_artifact",
    "insufficient_rows",
    "unproven",
]


class MaterializedArtifact(BaseModel):
    """One artifact payload known to have been produced by runtime."""

    model_config = ConfigDict(extra="forbid")

    artifact_key: str = Field(min_length=1, max_length=120)
    payload: Any


class ArtifactValidation(BaseModel):
    """Structural validation result for one materialized artifact."""

    model_config = ConfigDict(extra="forbid")

    artifact_key: str
    schema_known: bool
    valid: bool
    errors: tuple[str, ...] = ()
    grants_execution_authority: Literal[False] = False


class DeliverableFieldCompletion(BaseModel):
    """Materialization-time status of one requested deliverable field."""

    model_config = ConfigDict(extra="forbid")

    field_key: DeliverableFieldKey
    status: FieldCompletionStatus
    artifact_keys: tuple[str, ...] = ()
    observed_rows: int = 0
    required_rows: int = 0
    grants_execution_authority: Literal[False] = False


class DeliverableCompletion(BaseModel):
    """Requested-deliverable completion independent of task/job completion."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fields: tuple[DeliverableFieldCompletion, ...] = ()
    unresolved_request_items: tuple[str, ...] = ()
    grants_execution_authority: Literal[False] = False

    @property
    def complete(self) -> bool:
        return (
            bool(self.fields)
            and not self.unresolved_request_items
            and all(field.status == "satisfied" for field in self.fields)
        )


def _path_field(json_path: str) -> str | None:
    prefix = "$[]."
    if not json_path.startswith(prefix):
        return None
    field = json_path[len(prefix) :].strip()
    return field or None


def _artifact_has_value(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, (str, bytes, list, tuple, dict, set)):
        return bool(payload)
    return True


def validate_materialized_artifact(artifact: MaterializedArtifact) -> ArtifactValidation:
    """Validate a materialized payload against the typed schema catalog when one exists."""

    schema = ARTIFACT_SCHEMAS_BY_KEY.get(artifact.artifact_key)
    if schema is None:
        return ArtifactValidation(
            artifact_key=artifact.artifact_key,
            schema_known=False,
            valid=False,
            errors=("no typed artifact schema is declared",),
        )

    errors = validate_artifact_payload(schema, artifact.payload)
    return ArtifactValidation(
        artifact_key=artifact.artifact_key,
        schema_known=True,
        valid=not errors,
        errors=tuple(errors),
    )


def _typed_field_has_value(*, artifact: MaterializedArtifact, field_key: DeliverableFieldKey) -> bool:
    schema = ARTIFACT_SCHEMAS_BY_KEY.get(artifact.artifact_key)
    if schema is None:
        return False
    matching = [field for field in schema.fields if field.deliverable_field == field_key]
    if not matching:
        return False
    whole = [field for field in matching if field.scope == "whole_artifact"]
    if whole:
        if not isinstance(artifact.payload, dict):
            return False
        if field_key == "blocked_requests":
            # An empty list is a meaningful observation: the browser completed
            # with no blocked requests. Treat absence as unproven, but do not
            # confuse a clean network result with a missing artifact.
            return "blocked_requests" in artifact.payload and isinstance(artifact.payload["blocked_requests"], list)
        if field_key == "identity_gaps":
            # A verified identity has no gaps. Presence of an empty list is
            # therefore a satisfied observation; omission remains unproven.
            return "identity_gaps" in artifact.payload and isinstance(artifact.payload["identity_gaps"], list)
        if field_key in {"kpi_evaluations", "progress_gaps", "evidence_gaps"}:
            # Empty typed arrays are affirmative observations for a goal
            # evaluation. Presence is the proof; truthiness would erase it.
            key = next((field.json_path[2:].strip() for field in whole if field.json_path.startswith("$.")), None)
            return key is not None and key in artifact.payload and isinstance(artifact.payload[key], list)
        return all(
            field.json_path.startswith("$.") and bool(artifact.payload.get(field.json_path[2:].strip()))
            for field in whole
        )
    if not isinstance(artifact.payload, list) or not artifact.payload:
        return False
    for field in matching:
        path_field = _path_field(field.json_path)
        if path_field is None:
            return False
        if not all(
            isinstance(item, dict)
            and path_field in item
            and (
                _artifact_has_value(item[path_field])
                # An empty disqualifier list is a positive result: it proves
                # that no disqualifier was found for this prospect.
                or (field_key == "disqualifiers" and isinstance(item[path_field], list))
            )
            for item in artifact.payload
        ):
            return False
    return True


def evaluate_deliverable_completion(
    projection: DeliverableProjection,
    artifacts: tuple[MaterializedArtifact, ...] | list[MaterializedArtifact],
) -> DeliverableCompletion:
    """Evaluate requested fields without conflating structural binding with runtime completion."""

    artifacts_by_key = {artifact.artifact_key: artifact for artifact in artifacts}
    validations = {key: validate_materialized_artifact(artifact) for key, artifact in artifacts_by_key.items()}
    field_results: list[DeliverableFieldCompletion] = []

    for binding in projection.bindings:
        # Quantities constrain row-oriented artifacts. A whole-artifact report
        # can contain an internal list, but its requested fields are presence
        # checks; applying the mission quantity to the enclosing object would
        # incorrectly mark a valid report as insufficient_rows.
        whole_artifact_binding = any(
            field.deliverable_field == binding.field_key and field.scope == "whole_artifact"
            for artifact_key in binding.artifact_keys
            for field in (
                ARTIFACT_SCHEMAS_BY_KEY[artifact_key].fields if artifact_key in ARTIFACT_SCHEMAS_BY_KEY else ()
            )
        )
        required_rows = (
            0
            if whole_artifact_binding
            else max(
                (
                    projection.minimum_rows_by_artifact.get(artifact_key, projection.minimum_rows)
                    for artifact_key in binding.artifact_keys
                ),
                default=projection.minimum_rows,
            )
        )
        if binding.status != "bound":
            status: FieldCompletionStatus = "unproven"
        elif binding.basis == "whole_artifact_identity":
            present = [artifacts_by_key[key] for key in binding.artifact_keys if key in artifacts_by_key]
            status = (
                "satisfied"
                if any(_artifact_has_value(artifact.payload) for artifact in present)
                else "missing_artifact"
            )
        elif binding.basis == "typed_artifact_field":
            present = [artifacts_by_key[key] for key in binding.artifact_keys if key in artifacts_by_key]
            if not present:
                status = "missing_artifact"
            elif any(not validations[artifact.artifact_key].valid for artifact in present):
                status = "invalid_artifact"
            elif (
                required_rows
                and max(
                    (len(artifact.payload) for artifact in present if isinstance(artifact.payload, list)),
                    default=0,
                )
                < required_rows
            ):
                status = "insufficient_rows"
            elif any(_typed_field_has_value(artifact=artifact, field_key=binding.field_key) for artifact in present):
                status = "satisfied"
            else:
                status = "invalid_artifact"
        else:
            status = "unproven"

        field_results.append(
            DeliverableFieldCompletion(
                field_key=binding.field_key,
                status=status,
                artifact_keys=binding.artifact_keys,
                observed_rows=max(
                    (len(artifact.payload) for artifact in present if isinstance(artifact.payload, list)),
                    default=0,
                )
                if binding.basis == "typed_artifact_field"
                else 0,
                required_rows=(required_rows),
            )
        )

    return DeliverableCompletion(
        fields=tuple(field_results),
        unresolved_request_items=projection.request_unresolved_items,
    )
