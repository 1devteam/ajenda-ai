from __future__ import annotations

import pytest

from backend.services.vertical_ops.crm_reconciliation import (
    CanonicalCRMDesiredState,
    CRMLifecycleState,
    CRMOperationKind,
    CRMProviderObservation,
    plan_crm_reconciliation,
)
from backend.services.vertical_ops.graft1st_contracts import IdentityDecisionStatus, IdentityMatchDecision


def _identity(status: IdentityDecisionStatus = IdentityDecisionStatus.MATCHED) -> IdentityMatchDecision:
    return IdentityMatchDecision(
        decision_status=status,
        candidate_ids=("candidate-1",),
        canonical_entity_id="company:acme.example" if status == IdentityDecisionStatus.MATCHED else None,
        supporting_evidence_ids=("evidence-1",),
        rule_version="1.0.0",
        decided_by="identity.resolve_company",
    )


def _desired(state: CRMLifecycleState = CRMLifecycleState.RESOLVED) -> CanonicalCRMDesiredState:
    return CanonicalCRMDesiredState(
        canonical_entity_id="company:acme.example",
        object_type="account",
        lifecycle_state=state,
        fields={"name": "Acme AI", "domain": "acme.example"},
        source_artifact_ids=("artifact-1",),
    )


def _observation(state: CRMLifecycleState = CRMLifecycleState.OBSERVED) -> CRMProviderObservation:
    return CRMProviderObservation(
        provider="hubspot",
        provider_account_id="portal-1",
        provider_record_id="record-1",
        canonical_entity_id="company:acme.example",
        object_type="account",
        lifecycle_state=state,
        fields={"name": "Acme", "domain": "acme.example"},
        provider_version="version-1",
        observed_at_iso="2026-09-02T00:00:00Z",
    )


def test_missing_provider_record_produces_create_plan_without_authority() -> None:
    plan = plan_crm_reconciliation(desired=_desired(), identity_decision=_identity(), observation=None)
    assert plan.operation.operation_kind == CRMOperationKind.CREATE
    assert plan.grants_execution_authority is False
    assert plan.desired_state_hash.startswith("sha256:")


def test_matching_provider_state_produces_noop() -> None:
    observation = _observation(CRMLifecycleState.RESOLVED).model_copy(
        update={"fields": {"name": "Acme AI", "domain": "acme.example"}}
    )
    plan = plan_crm_reconciliation(desired=_desired(), identity_decision=_identity(), observation=observation)
    assert plan.operation.operation_kind == CRMOperationKind.NOOP


def test_update_is_bound_to_observed_provider_version() -> None:
    plan = plan_crm_reconciliation(desired=_desired(), identity_decision=_identity(), observation=_observation())
    assert plan.operation.operation_kind == CRMOperationKind.UPDATE
    assert plan.operation.expected_provider_version == "version-1"
    assert plan.operation.field_changes == {"name": "Acme AI"}
    assert plan.operation.lifecycle_to == CRMLifecycleState.RESOLVED


def test_ambiguous_identity_blocks_reconciliation() -> None:
    with pytest.raises(ValueError, match="non-ambiguous identity"):
        plan_crm_reconciliation(
            desired=_desired(),
            identity_decision=_identity(IdentityDecisionStatus.AMBIGUOUS),
            observation=None,
        )


def test_cross_entity_provider_link_becomes_conflict_not_overwrite() -> None:
    observation = _observation().model_copy(update={"canonical_entity_id": "company:other.example"})
    plan = plan_crm_reconciliation(desired=_desired(), identity_decision=_identity(), observation=observation)
    assert plan.operation.operation_kind == CRMOperationKind.CONFLICT
    assert not plan.operation.field_changes


def test_invalid_lifecycle_jump_fails_closed() -> None:
    with pytest.raises(ValueError, match="invalid canonical CRM lifecycle transition"):
        plan_crm_reconciliation(
            desired=_desired(CRMLifecycleState.CUSTOMER),
            identity_decision=_identity(),
            observation=_observation(CRMLifecycleState.RESOLVED),
        )
