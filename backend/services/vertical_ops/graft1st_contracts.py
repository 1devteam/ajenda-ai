"""Declarative G.R.A.F.T.1st contracts for the GTM/CRM communications vertical.

These models describe a future-state graph and its cross-window interfaces. They
do not register actions, resolve credentials, grant authority, persist state, or
dispatch work.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.records.contracts import (
    EffectCertainty as EffectCertainty,
    EffectReceiptContract as EffectReceiptContract,
    IdentityDecisionStatus as IdentityDecisionStatus,
    IdentityMatchDecision as IdentityMatchDecision,
)
from backend.services.tools.schemas import SideEffectClass

GRAFT1ST_CONTRACT_PACKAGE_ID = "revops.gtm-crm-communications"
GRAFT1ST_CONTRACT_PACKAGE_VERSION = "2.0.0"
ARTIFACT_ENVELOPE_SCHEMA_VERSION = 1

GRAFT1ST_REQUIRED_NODE_KEYS: frozenset[str] = frozenset(
    {
        "mission.interpret",
        "vertical.select",
        "graph.compile",
        "graph.adjudicate",
        "credential.preflight",
        "task.materialize",
        "research.discover",
        "research.extract_claims",
        "identity.resolve_company",
        "identity.resolve_person",
        "evidence.corroborate",
        "sales.qualify",
        "research.synthesize_report",
        "crm.observe",
        "crm.reconcile",
        "crm.mutate",
        "crm.verify_effect",
        "engagement.plan",
        "engagement.draft",
        "communication.authorize",
        "phone.receive_event",
        "phone.run_receptionist",
        "phone.transfer",
        "phone.initiate_outbound",
        "phone.finalize",
        "social.receive_event",
        "social.observe",
        "social.moderate",
        "social.reply",
        "social.publish",
        "social.verify_effect",
        "attribution.observe",
        "mission.reconcile",
        "outcome.review",
        "knowledge.qualify",
    }
)


class NodeImplementationStatus(StrEnum):
    CURRENT = "current"
    EXTEND = "extend"
    NEW = "new"
    ACTIVE_WORKTREE = "active_worktree"


class DependencyKind(StrEnum):
    HARD = "hard"
    CONDITIONAL = "conditional"
    OPTIONAL = "optional"
    AUTHORIZING = "authorizing"


class EdgeSemantics(StrEnum):
    REQUIRES = "requires"
    PRODUCES = "produces"
    VALIDATES = "validates"
    AUTHORIZES = "authorizes"
    RECONCILES = "reconciles"


class AdjudicationStatus(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INDETERMINATE = "indeterminate"


class StateAccessMode(StrEnum):
    READ = "read"
    WRITE = "write"
    CLAIM = "claim"


class SensitivityClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float = Field(ge=0, le=1)
    basis: str = Field(min_length=1, max_length=500)
    calibration_version: str | None = Field(default=None, max_length=80)


class ArtifactEnvelope(BaseModel):
    """Common provenance envelope; payload trust still depends on artifact type."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    artifact_id: str = Field(min_length=1, max_length=240)
    artifact_type: str = Field(min_length=1, max_length=160)
    artifact_schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    tenant_id: str = Field(min_length=1, max_length=160)
    mission_id: str = Field(min_length=1, max_length=160)
    producer_task_id: str = Field(min_length=1, max_length=160)
    producer_node_key: str = Field(min_length=1, max_length=160)
    created_at: datetime
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_artifact_ids: tuple[str, ...] = Field(default=(), max_length=500)
    confidence: Confidence | None = None
    limitations: tuple[str, ...] = Field(default=(), max_length=100)
    retention_class: str = Field(min_length=1, max_length=80)
    sensitivity_class: SensitivityClass
    payload: dict[str, Any]

    @field_validator("source_artifact_ids")
    @classmethod
    def canonicalize_source_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in values if item.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("source_artifact_ids must be unique")
        return normalized


class SideEffectAuthorizationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    tenant_id: str = Field(min_length=1, max_length=160)
    reviewer_principal_id: str = Field(min_length=1, max_length=160)
    task_id: str = Field(min_length=1, max_length=160)
    action_name: str = Field(min_length=1, max_length=160)
    capability_id: str = Field(min_length=1, max_length=160)
    adapter_id: str = Field(min_length=1, max_length=160)
    payload_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    destination: str = Field(min_length=1, max_length=500)
    side_effect_class: Literal[
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.EXTERNAL_PUBLISH,
    ]
    issued_at: datetime
    expires_at: datetime
    single_use: bool = True

    @model_validator(mode="after")
    def validate_expiry(self) -> SideEffectAuthorizationContract:
        if self.expires_at <= self.issued_at:
            raise ValueError("authorization expires_at must be after issued_at")
        return self


class CanonicalNodeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_key: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", max_length=160)
    owner: str = Field(min_length=1, max_length=160)
    implementation_status: NodeImplementationStatus
    accepts: tuple[str, ...] = Field(default=(), max_length=50)
    produces: tuple[str, ...] = Field(default=(), max_length=50)
    side_effect_class: SideEffectClass = SideEffectClass.NONE
    grants_execution_authority: Literal[False] = False

    @field_validator("accepts", "produces")
    @classmethod
    def validate_artifact_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip() for value in values if value.strip())
        if len(normalized) != len(set(normalized)):
            raise ValueError("node artifact names must be unique")
        return normalized


class CanonicalEdgeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(pattern=r"^E\d{2,3}$")
    consumer_node_key: str = Field(min_length=1, max_length=160)
    dependency_node_key: str = Field(min_length=1, max_length=160)
    artifact_type: str = Field(min_length=1, max_length=160)
    artifact_schema_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    dependency_kind: DependencyKind
    semantics: EdgeSemantics
    applicability_predicate: str | None = Field(default=None, max_length=500)
    adjudication_requirement: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_condition(self) -> CanonicalEdgeContract:
        if self.consumer_node_key == self.dependency_node_key:
            raise ValueError("canonical edge cannot depend on itself")
        if self.dependency_kind in {DependencyKind.CONDITIONAL, DependencyKind.OPTIONAL}:
            if not self.applicability_predicate:
                raise ValueError("conditional or optional edge requires applicability_predicate")
        if self.dependency_kind == DependencyKind.AUTHORIZING and self.semantics != EdgeSemantics.AUTHORIZES:
            raise ValueError("authorizing dependency must use authorizes semantics")
        return self


class CanonicalContractPackage(BaseModel):
    """Version-pinned, non-executable contract package shared across work windows."""

    model_config = ConfigDict(extra="forbid")

    package_id: Literal["revops.gtm-crm-communications"] = "revops.gtm-crm-communications"
    package_version: Literal["2.0.0"] = "2.0.0"
    authority_class: Literal["declarative"] = "declarative"
    grants_execution_authority: Literal[False] = False
    nodes: tuple[CanonicalNodeContract, ...] = Field(min_length=1, max_length=200)
    edges: tuple[CanonicalEdgeContract, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def validate_graph(self) -> CanonicalContractPackage:
        nodes_by_key = {node.node_key: node for node in self.nodes}
        if len(nodes_by_key) != len(self.nodes):
            raise ValueError("canonical node keys must be unique")
        missing_nodes = GRAFT1ST_REQUIRED_NODE_KEYS - set(nodes_by_key)
        unexpected_nodes = set(nodes_by_key) - GRAFT1ST_REQUIRED_NODE_KEYS
        if missing_nodes or unexpected_nodes:
            raise ValueError(
                "canonical node registry mismatch: "
                f"missing={sorted(missing_nodes)}, unexpected={sorted(unexpected_nodes)}"
            )
        if len({edge.edge_id for edge in self.edges}) != len(self.edges):
            raise ValueError("canonical edge ids must be unique")

        for edge in self.edges:
            consumer = nodes_by_key.get(edge.consumer_node_key)
            dependency = nodes_by_key.get(edge.dependency_node_key)
            if consumer is None or dependency is None:
                raise ValueError(f"edge {edge.edge_id} references an unknown node")
            if edge.artifact_type not in dependency.produces:
                raise ValueError(f"edge {edge.edge_id} artifact is not produced by dependency node")
            if edge.artifact_type not in consumer.accepts:
                raise ValueError(f"edge {edge.edge_id} artifact is not accepted by consumer node")

        self._assert_hard_dependency_acyclic()
        return self

    def _assert_hard_dependency_acyclic(self) -> None:
        dependencies: dict[str, set[str]] = {node.node_key: set() for node in self.nodes}
        for edge in self.edges:
            if edge.dependency_kind == DependencyKind.HARD:
                dependencies[edge.consumer_node_key].add(edge.dependency_node_key)
        remaining = set(dependencies)
        while remaining:
            ready = {key for key in remaining if not (dependencies[key] & remaining)}
            if not ready:
                raise ValueError("canonical hard dependencies contain a cycle")
            remaining -= ready


class SimulationStateAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_key: str = Field(min_length=1, max_length=240)
    mode: StateAccessMode


class InterminglingSimulationStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=120)
    node_key: str = Field(min_length=1, max_length=160)
    depends_on: tuple[str, ...] = Field(default=(), max_length=30)
    state_access: tuple[SimulationStateAccess, ...] = Field(default=(), max_length=30)
    expected_status: AdjudicationStatus = AdjudicationStatus.SATISFIED
    expected_reason: str = Field(min_length=1, max_length=500)


class InterminglingSimulationScenario(BaseModel):
    """Static ordering simulation; not provider, atomicity, or runtime proof."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    scenario_id: str = Field(pattern=r"^SIM-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=200)
    steps: tuple[InterminglingSimulationStep, ...] = Field(min_length=1, max_length=100)
    terminal_assertions: tuple[str, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_simulation(self) -> InterminglingSimulationScenario:
        steps_by_id = {step.step_id: step for step in self.steps}
        if len(steps_by_id) != len(self.steps):
            raise ValueError("simulation step ids must be unique")
        for step in self.steps:
            if step.node_key not in GRAFT1ST_REQUIRED_NODE_KEYS:
                raise ValueError(f"simulation step references unknown canonical node: {step.node_key}")
            missing = set(step.depends_on) - set(steps_by_id)
            if missing:
                raise ValueError(f"simulation step {step.step_id} has unknown dependencies: {sorted(missing)}")
            if step.step_id in step.depends_on:
                raise ValueError(f"simulation step {step.step_id} cannot depend on itself")

        ancestors = self._ancestor_map(steps_by_id)
        for index, left in enumerate(self.steps):
            left_access = {access.resource_key: access.mode for access in left.state_access}
            for right in self.steps[index + 1 :]:
                ordered = right.step_id in ancestors[left.step_id] or left.step_id in ancestors[right.step_id]
                if ordered:
                    continue
                for access in right.state_access:
                    left_mode = left_access.get(access.resource_key)
                    if left_mode is not None and (
                        left_mode != StateAccessMode.READ or access.mode != StateAccessMode.READ
                    ):
                        raise ValueError(
                            "unordered simulation state collision: "
                            f"{left.step_id} and {right.step_id} access {access.resource_key}"
                        )
        return self

    @staticmethod
    def _ancestor_map(
        steps_by_id: dict[str, InterminglingSimulationStep],
    ) -> dict[str, set[str]]:
        ancestors: dict[str, set[str]] = {step_id: set() for step_id in steps_by_id}
        unresolved = set(steps_by_id)
        while unresolved:
            progressed = False
            for step_id in tuple(unresolved):
                dependencies = set(steps_by_id[step_id].depends_on)
                if dependencies & unresolved:
                    continue
                ancestors[step_id] = dependencies | {
                    ancestor for dependency in dependencies for ancestor in ancestors[dependency]
                }
                unresolved.remove(step_id)
                progressed = True
            if not progressed:
                raise ValueError("simulation dependencies contain a cycle")
        return ancestors


class InterminglingSimulationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: Literal["gtm-crm-communications-intermingling"] = "gtm-crm-communications-intermingling"
    schema_version: Literal[1] = 1
    contract_package_version: Literal["2.0.0"] = "2.0.0"
    scenarios: tuple[InterminglingSimulationScenario, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_scenario_ids(self) -> InterminglingSimulationSuite:
        if len({scenario.scenario_id for scenario in self.scenarios}) != len(self.scenarios):
            raise ValueError("simulation scenario ids must be unique")
        return self


def assert_compatible_contract_version(*, declared: str, supported_major: int) -> None:
    """Fail closed when a consumer sees an unsupported contract major version."""

    try:
        major_text, minor_text, patch_text = declared.split(".")
        parts = (int(major_text), int(minor_text), int(patch_text))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid semantic contract version: {declared!r}") from exc
    if any(part < 0 for part in parts) or parts[0] == 0:
        raise ValueError(f"invalid semantic contract version: {declared!r}")
    if parts[0] != supported_major:
        raise ValueError(f"unsupported contract major version: {parts[0]}")
