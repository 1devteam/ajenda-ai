"""Typed lifecycle contracts for Ajenda graph and GRAFT artifacts.

These contracts describe ownership, freshness, retention, tenant scope, and
historical lineage for graph-produced artifacts. They are governance metadata,
not runtime authority: no contract in this module dispatches work, resolves
secrets, or mutates tenant state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GRAFT_ARTIFACT_LIFECYCLE_SCHEMA_VERSION: Literal[1] = 1

ArtifactAuthorityClass = Literal["diagnostic", "read_only_observation", "declarative"]
ArtifactTenantScope = Literal["none", "tenant_scoped", "mixed"]
ArtifactLifecycleState = Literal["current", "superseded", "archived"]


class GraftArtifactLifecycleContract(BaseModel):
    """Ownership and lifecycle policy for one graph/GRAFT artifact type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = GRAFT_ARTIFACT_LIFECYCLE_SCHEMA_VERSION
    artifact_type: str = Field(min_length=1, max_length=160)
    artifact_schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    owner: str = Field(min_length=1, max_length=160)
    producer: str = Field(min_length=1, max_length=240)
    authority_class: ArtifactAuthorityClass
    tenant_scope: ArtifactTenantScope
    retention_class: str = Field(min_length=1, max_length=80)
    freshness_window_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    historical_read_compatible: bool = True
    consumers: tuple[str, ...] = Field(min_length=1, max_length=30)
    grants_execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_lifecycle_policy(self) -> GraftArtifactLifecycleContract:
        if self.authority_class == "read_only_observation" and self.tenant_scope == "none":
            raise ValueError("tenant-scoped observation artifacts cannot have tenant_scope=none")
        if len(set(self.consumers)) != len(self.consumers):
            raise ValueError("artifact consumers must be unique")
        return self


class GraftArtifactLifecycleRecord(BaseModel):
    """Immutable provenance record for one generated graph/GRAFT artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = GRAFT_ARTIFACT_LIFECYCLE_SCHEMA_VERSION
    artifact_id: str = Field(min_length=1, max_length=240)
    artifact_type: str = Field(min_length=1, max_length=160)
    artifact_schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    source_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$", max_length=64)
    created_at: datetime
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    lifecycle_state: ArtifactLifecycleState = "current"
    tenant_id: str | None = Field(default=None, min_length=1, max_length=160)
    supersedes_artifact_id: str | None = Field(default=None, min_length=1, max_length=240)
    authority_class: ArtifactAuthorityClass
    grants_execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def validate_lineage(self) -> GraftArtifactLifecycleRecord:
        if self.lifecycle_state == "superseded" and not self.supersedes_artifact_id:
            raise ValueError("superseded artifact requires supersedes_artifact_id")
        if self.lifecycle_state == "current" and self.supersedes_artifact_id:
            raise ValueError("current artifact cannot supersede another artifact")
        return self


GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS: tuple[GraftArtifactLifecycleContract, ...] = (
    GraftArtifactLifecycleContract(
        artifact_type="canonical_dependency_graph",
        artifact_schema_version="1.0.0",
        owner="architecture-runtime-governance",
        producer="scripts/validation/build_dependency_graph.py",
        authority_class="diagnostic",
        tenant_scope="none",
        retention_class="build_evidence",
        freshness_window_seconds=86_400,
        consumers=("graph_impact_analysis", "graph_completeness_audit", "graph_proof_selection"),
    ),
    GraftArtifactLifecycleContract(
        artifact_type="graft_impact_report",
        artifact_schema_version="1.0.0",
        owner="architecture-runtime-governance",
        producer="scripts/validation/graph_impact_analysis.py",
        authority_class="diagnostic",
        tenant_scope="none",
        retention_class="review_evidence",
        freshness_window_seconds=86_400,
        consumers=("graph_proof_selection", "pull_request_review", "graph_runtime_impact"),
    ),
    GraftArtifactLifecycleContract(
        artifact_type="graft_runtime_admission_report",
        artifact_schema_version="1.0.0",
        owner="runtime-admission-governance",
        producer="backend/services/mission_graph_integrity.py",
        authority_class="read_only_observation",
        tenant_scope="tenant_scoped",
        retention_class="mission_runtime_evidence",
        freshness_window_seconds=0,
        consumers=("runtime_admission_route", "mission_runtime_evidence_review"),
    ),
    GraftArtifactLifecycleContract(
        artifact_type="graft_runtime_evidence",
        artifact_schema_version="1.0.0",
        owner="evidence-observability-governance",
        producer="backend/services/mission_runtime_evidence_projection.py",
        authority_class="read_only_observation",
        tenant_scope="tenant_scoped",
        retention_class="mission_runtime_evidence",
        freshness_window_seconds=0,
        consumers=("runtime_evidence_route", "graph_runtime_impact"),
    ),
    GraftArtifactLifecycleContract(
        artifact_type="graft1st_revops_contract_package",
        artifact_schema_version="2.0.0",
        owner="revops-composition-governance",
        producer="backend/services/vertical_ops/graft1st_contracts.py",
        authority_class="declarative",
        tenant_scope="none",
        retention_class="versioned_contract",
        freshness_window_seconds=None,
        historical_read_compatible=True,
        consumers=("vertical_know_how", "graft_plus_graft1st_reconciliation"),
    ),
)


GRAFT_ARTIFACT_LIFECYCLE_BY_TYPE = {item.artifact_type: item for item in GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS}


def validate_graft_artifact_lifecycle_registry() -> None:
    """Fail closed when lifecycle contracts duplicate or grant authority."""

    if len(GRAFT_ARTIFACT_LIFECYCLE_BY_TYPE) != len(GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS):
        raise ValueError("GRAFT artifact lifecycle artifact types must be unique")
    for contract in GRAFT_ARTIFACT_LIFECYCLE_CONTRACTS:
        if contract.grants_execution_authority:
            raise ValueError(f"GRAFT artifact lifecycle contract grants authority: {contract.artifact_type}")


validate_graft_artifact_lifecycle_registry()
