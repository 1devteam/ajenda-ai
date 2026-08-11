"""Typed evidence origin and lineage contracts.

Artifact identity, source identity, derivation, and resolution are deliberately
separate.  Absence of lineage never proves independent origin.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceOriginType(StrEnum):
    SOURCE_OBSERVATION = "source_observation"
    DERIVED_FACT = "derived_fact"
    AGGREGATION = "aggregation"
    CALLER_ASSERTION = "caller_assertion"
    SYSTEM_COMPUTATION = "system_computation"
    UNKNOWN = "unknown"


class EvidenceLineageResolution(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class EvidenceSourceIdentity(BaseModel):
    """Opaque owner-defined source record identity; values remain case-sensitive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_system: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=240)

    @field_validator("source_system", "source_record_id")
    @classmethod
    def strip_nonempty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source identity values must be non-empty")
        return normalized


class EvidenceLineage(BaseModel):
    """Owner-produced lineage for one evidence artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    artifact_evidence_id: str = Field(min_length=1, max_length=240)
    origin_type: EvidenceOriginType = EvidenceOriginType.UNKNOWN
    source_identity: EvidenceSourceIdentity | None = None
    root_evidence_ids: tuple[str, ...] = ()
    parent_evidence_ids: tuple[str, ...] = ()
    ancestor_evidence_ids: tuple[str, ...] = ()
    resolution: EvidenceLineageResolution = EvidenceLineageResolution.UNKNOWN

    @field_validator("artifact_evidence_id")
    @classmethod
    def normalize_artifact_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("artifact_evidence_id must be non-empty")
        return normalized

    @field_validator("root_evidence_ids", "parent_evidence_ids", "ancestor_evidence_ids")
    @classmethod
    def canonicalize_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({value.strip() for value in values if value.strip()}))

    @model_validator(mode="after")
    def validate_resolution_claim(self) -> EvidenceLineage:
        has_identity = bool(
            self.source_identity or self.root_evidence_ids or self.parent_evidence_ids or self.ancestor_evidence_ids
        )
        if self.resolution == EvidenceLineageResolution.KNOWN and not has_identity:
            raise ValueError("known lineage requires source, root, parent, or ancestor identity")
        if self.resolution == EvidenceLineageResolution.UNKNOWN and has_identity:
            raise ValueError("unknown lineage cannot contain resolved lineage identity")
        return self

    def dependence_keys(self) -> frozenset[str]:
        """Return opaque keys that establish a known shared lineage."""

        keys = {f"evidence:{self.artifact_evidence_id}"}
        keys.update(
            {
                f"evidence:{item}"
                for item in (*self.root_evidence_ids, *self.parent_evidence_ids, *self.ancestor_evidence_ids)
            }
        )
        if self.source_identity is not None:
            keys.add(f"source:{self.source_identity.source_system}:{self.source_identity.source_record_id}")
        return frozenset(keys)
