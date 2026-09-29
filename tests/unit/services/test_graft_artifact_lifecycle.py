from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.services.graft_artifact_lifecycle import (
    GRAFT_ARTIFACT_LIFECYCLE_BY_TYPE,
    GraftArtifactLifecycleRecord,
    validate_graft_artifact_lifecycle_registry,
)


def test_graft_artifact_lifecycle_registry_is_unique_and_non_authoritative() -> None:
    validate_graft_artifact_lifecycle_registry()

    assert set(GRAFT_ARTIFACT_LIFECYCLE_BY_TYPE) == {
        "canonical_dependency_graph",
        "graft_impact_report",
        "graft_runtime_admission_report",
        "graft_runtime_evidence",
        "graft1st_revops_contract_package",
    }
    assert all(not contract.grants_execution_authority for contract in GRAFT_ARTIFACT_LIFECYCLE_BY_TYPE.values())


def test_tenant_scoped_observation_requires_tenant_scope() -> None:
    from backend.services.graft_artifact_lifecycle import GraftArtifactLifecycleContract

    with pytest.raises(ValidationError, match="tenant_scope=none"):
        GraftArtifactLifecycleContract(
            artifact_type="invalid",
            artifact_schema_version="1.0.0",
            owner="owner",
            producer="producer",
            authority_class="read_only_observation",
            tenant_scope="none",
            retention_class="test",
            consumers=("consumer",),
        )


def test_current_artifact_cannot_claim_supersession() -> None:
    with pytest.raises(ValidationError, match="current artifact cannot supersede"):
        GraftArtifactLifecycleRecord(
            artifact_id="artifact-current",
            artifact_type="graft_runtime_evidence",
            artifact_schema_version="1.0.0",
            source_commit="42768eb3",
            created_at=datetime.now(UTC),
            content_hash="sha256:" + "a" * 64,
            lifecycle_state="current",
            supersedes_artifact_id="artifact-old",
            authority_class="read_only_observation",
        )


def test_superseded_artifact_requires_lineage() -> None:
    with pytest.raises(ValidationError, match="superseded artifact requires"):
        GraftArtifactLifecycleRecord(
            artifact_id="artifact-old",
            artifact_type="graft_runtime_evidence",
            artifact_schema_version="1.0.0",
            source_commit="42768eb3",
            created_at=datetime.now(UTC),
            content_hash="sha256:" + "b" * 64,
            lifecycle_state="superseded",
            authority_class="read_only_observation",
        )
