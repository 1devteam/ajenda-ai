"""Canonical CRM lifecycle and provider-neutral reconciliation contracts.

The planner produces desired operations only. It does not persist canonical
state, invoke a provider, grant approval, or claim that an effect occurred.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.vertical_ops.graft1st_contracts import IdentityDecisionStatus, IdentityMatchDecision


class CRMLifecycleState(StrEnum):
    OBSERVED = "observed"
    RESOLVED = "resolved"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"
    ENGAGING = "engaging"
    NURTURE = "nurture"
    OPPORTUNITY = "opportunity"
    CUSTOMER = "customer"
    CLOSED_LOST = "closed_lost"
    EXPANSION = "expansion"


class CRMOperationKind(StrEnum):
    NOOP = "noop"
    CREATE = "create"
    UPDATE = "update"
    ASSOCIATE = "associate"
    CONFLICT = "conflict"


ALLOWED_LIFECYCLE_TRANSITIONS: dict[CRMLifecycleState, frozenset[CRMLifecycleState]] = {
    CRMLifecycleState.OBSERVED: frozenset({CRMLifecycleState.RESOLVED}),
    CRMLifecycleState.RESOLVED: frozenset({CRMLifecycleState.QUALIFIED, CRMLifecycleState.DISQUALIFIED}),
    CRMLifecycleState.QUALIFIED: frozenset({CRMLifecycleState.ENGAGING}),
    CRMLifecycleState.ENGAGING: frozenset({CRMLifecycleState.OPPORTUNITY, CRMLifecycleState.NURTURE}),
    CRMLifecycleState.NURTURE: frozenset({CRMLifecycleState.ENGAGING}),
    CRMLifecycleState.OPPORTUNITY: frozenset({CRMLifecycleState.CUSTOMER, CRMLifecycleState.CLOSED_LOST}),
    CRMLifecycleState.CUSTOMER: frozenset({CRMLifecycleState.EXPANSION}),
    CRMLifecycleState.DISQUALIFIED: frozenset(),
    CRMLifecycleState.CLOSED_LOST: frozenset(),
    CRMLifecycleState.EXPANSION: frozenset(),
}


class CanonicalCRMDesiredState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    canonical_entity_id: str = Field(min_length=1, max_length=160)
    object_type: str = Field(min_length=1, max_length=80)
    lifecycle_state: CRMLifecycleState
    fields: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=100)
    association_entity_ids: tuple[str, ...] = Field(default=(), max_length=100)
    source_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=200)


class CRMProviderObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    provider: str = Field(min_length=1, max_length=120)
    provider_account_id: str = Field(min_length=1, max_length=160)
    provider_record_id: str = Field(min_length=1, max_length=160)
    canonical_entity_id: str | None = Field(default=None, max_length=160)
    object_type: str = Field(min_length=1, max_length=80)
    lifecycle_state: CRMLifecycleState | None = None
    fields: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=100)
    association_entity_ids: tuple[str, ...] = Field(default=(), max_length=100)
    provider_version: str = Field(min_length=1, max_length=240)
    observed_at_iso: str = Field(min_length=1, max_length=80)


class CRMReconciliationOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_kind: CRMOperationKind
    provider_record_id: str | None = Field(default=None, max_length=160)
    expected_provider_version: str | None = Field(default=None, max_length=240)
    field_changes: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=100)
    association_additions: tuple[str, ...] = Field(default=(), max_length=100)
    lifecycle_from: CRMLifecycleState | None = None
    lifecycle_to: CRMLifecycleState | None = None
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_operation(self) -> CRMReconciliationOperation:
        if self.operation_kind in {CRMOperationKind.UPDATE, CRMOperationKind.ASSOCIATE}:
            if not self.provider_record_id or not self.expected_provider_version:
                raise ValueError("provider mutation operation requires record id and observed version")
        if self.operation_kind == CRMOperationKind.NOOP and (
            self.field_changes or self.association_additions or self.lifecycle_to is not None
        ):
            raise ValueError("noop operation cannot contain mutations")
        return self


class CRMReconciliationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    plan_id: str = Field(min_length=1, max_length=160)
    canonical_entity_id: str = Field(min_length=1, max_length=160)
    desired_state_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observation_version: str | None = Field(default=None, max_length=240)
    operation: CRMReconciliationOperation
    source_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=200)
    grants_execution_authority: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> CRMReconciliationPlan:
        if self.grants_execution_authority:
            raise ValueError("CRM reconciliation plan cannot grant execution authority")
        return self


def validate_lifecycle_transition(
    *,
    current: CRMLifecycleState | None,
    desired: CRMLifecycleState,
) -> None:
    if current is None or current == desired:
        return
    if desired not in ALLOWED_LIFECYCLE_TRANSITIONS[current]:
        raise ValueError(f"invalid canonical CRM lifecycle transition: {current.value}->{desired.value}")


def plan_crm_reconciliation(
    *,
    desired: CanonicalCRMDesiredState,
    identity_decision: IdentityMatchDecision,
    observation: CRMProviderObservation | None,
) -> CRMReconciliationPlan:
    if identity_decision.decision_status not in {
        IdentityDecisionStatus.MATCHED,
        IdentityDecisionStatus.NEW,
    }:
        raise ValueError("CRM reconciliation requires resolved, non-ambiguous identity")
    if identity_decision.canonical_entity_id and identity_decision.canonical_entity_id != desired.canonical_entity_id:
        raise ValueError("identity decision does not match desired canonical entity")
    desired_hash = _desired_state_hash(desired)

    if observation is None:
        operation = CRMReconciliationOperation(
            operation_kind=CRMOperationKind.CREATE,
            field_changes=desired.fields,
            association_additions=desired.association_entity_ids,
            lifecycle_to=desired.lifecycle_state,
            reason="No provider record was observed for the resolved canonical entity.",
        )
        observation_version = None
    elif observation.canonical_entity_id not in {None, desired.canonical_entity_id}:
        operation = CRMReconciliationOperation(
            operation_kind=CRMOperationKind.CONFLICT,
            provider_record_id=observation.provider_record_id,
            expected_provider_version=observation.provider_version,
            reason="Provider record is linked to a different canonical entity.",
        )
        observation_version = observation.provider_version
    else:
        validate_lifecycle_transition(current=observation.lifecycle_state, desired=desired.lifecycle_state)
        field_changes = {key: value for key, value in desired.fields.items() if observation.fields.get(key) != value}
        association_additions = tuple(
            sorted(set(desired.association_entity_ids) - set(observation.association_entity_ids))
        )
        lifecycle_changed = observation.lifecycle_state != desired.lifecycle_state
        if not field_changes and not association_additions and not lifecycle_changed:
            operation = CRMReconciliationOperation(
                operation_kind=CRMOperationKind.NOOP,
                provider_record_id=observation.provider_record_id,
                expected_provider_version=observation.provider_version,
                reason="Observed provider state already matches desired canonical state.",
            )
        else:
            operation = CRMReconciliationOperation(
                operation_kind=CRMOperationKind.UPDATE,
                provider_record_id=observation.provider_record_id,
                expected_provider_version=observation.provider_version,
                field_changes=field_changes,
                association_additions=association_additions,
                lifecycle_from=observation.lifecycle_state,
                lifecycle_to=desired.lifecycle_state if lifecycle_changed else None,
                reason="Observed provider state differs from desired canonical state.",
            )
        observation_version = observation.provider_version

    return CRMReconciliationPlan(
        plan_id=f"crm-plan-{desired_hash.removeprefix('sha256:')[:16]}",
        canonical_entity_id=desired.canonical_entity_id,
        desired_state_hash=desired_hash,
        observation_version=observation_version,
        operation=operation,
        source_artifact_ids=desired.source_artifact_ids,
    )


def _desired_state_hash(desired: CanonicalCRMDesiredState) -> str:
    payload: dict[str, Any] = desired.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
