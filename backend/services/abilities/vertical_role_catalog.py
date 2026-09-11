"""Declarative vertical role catalog (ADR-0007 Phase A).

Vertical roles group ability/action bindings for mission planning. They are
declarative contracts only:

- They do not register ActionRegistry handlers.
- They do not enqueue work, claim leases, or invoke tools.
- They do not grant runtime execution authority (PROJECT_SPEC invariant 6).

Runtime execution remains:
Mission → mission_bridge → ExecutionCoordinator → WorkerLoop lease →
TaskDispatcher → tool.invoke → ToolRuntimeAuthority → ActionRegistry.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.auth.permissions import Permission
from backend.domain.compliance import (
    ComplianceCategory,
    is_supported_compliance_category,
    is_supported_jurisdiction,
)
from backend.services.abilities.manifest import AbilityRiskLevel
from backend.services.tools.schemas import SideEffectClass

_CANONICAL_PERMISSIONS: frozenset[str] = frozenset(item.value for item in Permission)

_WRITE_OR_SEND_EFFECTS = {
    SideEffectClass.INTERNAL_WRITE,
    SideEffectClass.EXTERNAL_WRITE,
    SideEffectClass.EXTERNAL_SEND,
    SideEffectClass.EXTERNAL_PUBLISH,
}

_EXTERNAL_MUTATING_EFFECTS = {
    SideEffectClass.EXTERNAL_WRITE,
    SideEffectClass.EXTERNAL_SEND,
    SideEffectClass.EXTERNAL_PUBLISH,
}

_HIGH_REVIEW_CATEGORIES = {
    ComplianceCategory.EMPLOYMENT.value,
    ComplianceCategory.FINANCIAL.value,
    ComplianceCategory.HEALTHCARE.value,
    ComplianceCategory.CONSUMER_INTERACTION.value,
    ComplianceCategory.PUBLIC_CONTENT.value,
}


class RoleBindingStatus(StrEnum):
    """Whether a binding points at a real action or is catalog-only deferred."""

    RUNTIME_BOUND = "runtime_bound"
    CATALOG_ONLY = "catalog_only"


class VerticalRoleBinding(BaseModel):
    """One role → action binding. Declarative; not an execution grant."""

    model_config = ConfigDict(extra="forbid")

    action_name: str = Field(min_length=1, max_length=160)
    binding_status: RoleBindingStatus
    capability_name: str = Field(min_length=1, max_length=160)
    capability_version: str = Field(min_length=1, max_length=80)
    adapter_name: str = Field(min_length=1, max_length=160)
    adapter_version: str = Field(min_length=1, max_length=80)
    side_effect_class: SideEffectClass
    risk_level: AbilityRiskLevel
    required_permissions: tuple[str, ...] = ()
    approval_required: bool = False
    idempotency_required: bool = False
    idempotency_contract_ref: str | None = Field(default=None, max_length=240)
    evidence_required: bool = True
    evidence_expectations: tuple[str, ...] = ()
    readback_required: bool = False
    readback_deferred_reason: str | None = Field(default=None, max_length=500)
    requires_human_review: bool = False
    enabled_by_default: bool = False
    credential_required: bool = False
    deferred_reason: str | None = Field(default=None, max_length=500)

    @field_validator(
        "action_name",
        "capability_name",
        "capability_version",
        "adapter_name",
        "adapter_version",
    )
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("idempotency_contract_ref", "readback_deferred_reason", "deferred_reason")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("required_permissions")
    @classmethod
    def normalize_permissions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("required_permissions entries must be non-empty")
            if stripped not in _CANONICAL_PERMISSIONS:
                raise ValueError(f"unknown permission: {stripped}")
            if stripped in normalized:
                raise ValueError(f"duplicate permission: {stripped}")
            normalized.append(stripped)
        return tuple(normalized)

    @field_validator("evidence_expectations")
    @classmethod
    def normalize_evidence_expectations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("evidence_expectations entries must be non-empty")
            if stripped in normalized:
                raise ValueError("evidence_expectations entries must be unique")
            normalized.append(stripped)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_binding_policy(self) -> VerticalRoleBinding:
        if self.binding_status is RoleBindingStatus.CATALOG_ONLY and not self.deferred_reason:
            raise ValueError("catalog_only bindings require deferred_reason")
        if self.binding_status is RoleBindingStatus.RUNTIME_BOUND and self.deferred_reason:
            raise ValueError("runtime_bound bindings must not set deferred_reason")

        if self.side_effect_class.has_side_effect and not self.approval_required:
            raise ValueError("side-effecting bindings require approval_required=true")
        if self.side_effect_class.value.startswith("external_") and not self.approval_required:
            raise ValueError("external bindings require approval_required=true")
        if self.side_effect_class in _EXTERNAL_MUTATING_EFFECTS and not self.idempotency_required:
            raise ValueError("external write/send/publish bindings require idempotency_required=true")
        if self.idempotency_required and not self.idempotency_contract_ref:
            raise ValueError("idempotency-required bindings require idempotency_contract_ref")
        if not self.evidence_required:
            raise ValueError("vertical role bindings require evidence_required=true")
        if self.evidence_required and not self.evidence_expectations:
            raise ValueError("evidence-required bindings require evidence_expectations")
        if self.side_effect_class in _WRITE_OR_SEND_EFFECTS and not self.readback_required:
            if not self.readback_deferred_reason:
                raise ValueError("write/send/publish bindings require readback_required=true or a deferred reason")
        if self.enabled_by_default and self.risk_level in {
            AbilityRiskLevel.HIGH,
            AbilityRiskLevel.CRITICAL,
        }:
            raise ValueError("high or critical risk bindings cannot be enabled by default")
        if self.enabled_by_default and self.side_effect_class.value.startswith("external_"):
            raise ValueError("external bindings cannot be enabled by default")
        if self.enabled_by_default and self.approval_required:
            raise ValueError("approval-required bindings cannot be enabled by default")
        if self.side_effect_class in _EXTERNAL_MUTATING_EFFECTS and not self.credential_required:
            # External mutations without credentials are catalog theater unless deferred.
            if self.binding_status is RoleBindingStatus.RUNTIME_BOUND:
                raise ValueError("runtime-bound external write/send/publish requires credential_required=true")
        return self


class VerticalRoleSpec(BaseModel):
    """One vertical role: catalog grouping for mission planning, not an agent runtime."""

    model_config = ConfigDict(extra="forbid")

    role_key: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1000)
    risk_level: AbilityRiskLevel
    compliance_category: str = Field(min_length=1, max_length=80)
    default_jurisdiction: str = Field(min_length=1, max_length=32)
    requires_human_review: bool = False
    required_permissions: tuple[str, ...] = ()
    evidence_expectations: tuple[str, ...] = ()
    bindings: tuple[VerticalRoleBinding, ...] = ()
    enabled_by_default: bool = False
    authority_class: Literal["declarative"] = "declarative"
    notes: str = Field(min_length=1, max_length=1000)

    @field_validator("role_key", "display_name", "description", "notes")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("compliance_category")
    @classmethod
    def validate_compliance_category(cls, value: str) -> str:
        stripped = value.strip()
        if not is_supported_compliance_category(stripped):
            raise ValueError(f"unsupported compliance_category: {stripped}")
        return stripped

    @field_validator("default_jurisdiction")
    @classmethod
    def validate_jurisdiction(cls, value: str) -> str:
        stripped = value.strip()
        if not is_supported_jurisdiction(stripped):
            raise ValueError(f"unsupported jurisdiction: {stripped}")
        return stripped

    @field_validator("required_permissions")
    @classmethod
    def normalize_permissions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("required_permissions entries must be non-empty")
            if stripped not in _CANONICAL_PERMISSIONS:
                raise ValueError(f"unknown permission: {stripped}")
            if stripped in normalized:
                raise ValueError(f"duplicate permission: {stripped}")
            normalized.append(stripped)
        return tuple(normalized)

    @field_validator("evidence_expectations")
    @classmethod
    def normalize_evidence_expectations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("evidence_expectations entries must be non-empty")
            if stripped in normalized:
                raise ValueError("evidence_expectations entries must be unique")
            normalized.append(stripped)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_role_policy(self) -> VerticalRoleSpec:
        if not self.role_key.startswith("vertical."):
            raise ValueError("role_key must be namespaced as vertical.*")
        if not self.bindings:
            raise ValueError("vertical roles require at least one binding")
        if not self.evidence_expectations:
            raise ValueError("vertical roles require evidence_expectations")
        if self.enabled_by_default and self.risk_level in {
            AbilityRiskLevel.HIGH,
            AbilityRiskLevel.CRITICAL,
        }:
            raise ValueError("high or critical risk roles cannot be enabled by default")
        if self.risk_level in {AbilityRiskLevel.HIGH, AbilityRiskLevel.CRITICAL}:
            if not self.requires_human_review:
                raise ValueError("high or critical risk roles require requires_human_review=true")
        if self.compliance_category in _HIGH_REVIEW_CATEGORIES and not self.requires_human_review:
            raise ValueError(f"compliance_category '{self.compliance_category}' requires requires_human_review=true")
        action_names = [binding.action_name for binding in self.bindings]
        if len(action_names) != len(set(action_names)):
            raise ValueError("role bindings must have unique action_name values")
        # Role-level permissions must be a superset of binding permissions for planning clarity.
        role_perms = set(self.required_permissions)
        for binding in self.bindings:
            missing = set(binding.required_permissions) - role_perms
            if missing:
                raise ValueError(f"role required_permissions missing binding permissions: {sorted(missing)}")
            if binding.risk_level is AbilityRiskLevel.CRITICAL and self.risk_level is not AbilityRiskLevel.CRITICAL:
                raise ValueError("role risk_level must be critical when any binding is critical")
        return self


class VerticalRolePack(BaseModel):
    """Versioned declarative pack of vertical roles. Not a runtime orchestrator."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1000)
    roles: tuple[VerticalRoleSpec, ...]
    authority_class: Literal["declarative"] = "declarative"
    grants_execution_authority: Literal[False] = False
    schema_version: Literal[1] = 1

    @field_validator("pack_id", "version", "display_name", "description")
    @classmethod
    def strip_required_strings(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @model_validator(mode="after")
    def validate_pack(self) -> VerticalRolePack:
        if not self.roles:
            raise ValueError("pack requires at least one role")
        role_keys = [role.role_key for role in self.roles]
        if len(role_keys) != len(set(role_keys)):
            raise ValueError("pack roles must have unique role_key values")
        if self.grants_execution_authority:
            raise ValueError("vertical role packs must not grant execution authority")
        return self


def get_vertical_role(role_key: str, *, pack: VerticalRolePack | None = None) -> VerticalRoleSpec:
    """Lookup a role by key from the default pack or a provided pack."""

    target = pack or VERTICAL_OPS_PACK
    for role in target.roles:
        if role.role_key == role_key:
            return role
    raise ValueError(f"unknown vertical role_key: {role_key}")


def list_runtime_bound_action_names(*, pack: VerticalRolePack | None = None) -> tuple[str, ...]:
    """Return unique runtime-bound action names (still not an execution grant)."""

    target = pack or VERTICAL_OPS_PACK
    names: list[str] = []
    for role in target.roles:
        for binding in role.bindings:
            if binding.binding_status is RoleBindingStatus.RUNTIME_BOUND and binding.action_name not in names:
                names.append(binding.action_name)
    return tuple(names)


def _runtime_binding(
    *,
    action_name: str,
    capability_name: str,
    capability_version: str,
    adapter_name: str,
    adapter_version: str,
    side_effect_class: SideEffectClass,
    risk_level: AbilityRiskLevel,
    required_permissions: tuple[str, ...],
    approval_required: bool,
    idempotency_required: bool = False,
    idempotency_contract_ref: str | None = None,
    evidence_expectations: tuple[str, ...],
    readback_required: bool = False,
    readback_deferred_reason: str | None = None,
    requires_human_review: bool = False,
    credential_required: bool = False,
) -> VerticalRoleBinding:
    return VerticalRoleBinding(
        action_name=action_name,
        binding_status=RoleBindingStatus.RUNTIME_BOUND,
        capability_name=capability_name,
        capability_version=capability_version,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        side_effect_class=side_effect_class,
        risk_level=risk_level,
        required_permissions=required_permissions,
        approval_required=approval_required,
        idempotency_required=idempotency_required,
        idempotency_contract_ref=idempotency_contract_ref,
        evidence_required=True,
        evidence_expectations=evidence_expectations,
        readback_required=readback_required,
        readback_deferred_reason=readback_deferred_reason,
        requires_human_review=requires_human_review,
        enabled_by_default=False,
        credential_required=credential_required,
    )


def _catalog_only_binding(
    *,
    action_name: str,
    capability_name: str,
    adapter_name: str,
    side_effect_class: SideEffectClass,
    risk_level: AbilityRiskLevel,
    required_permissions: tuple[str, ...],
    evidence_expectations: tuple[str, ...],
    deferred_reason: str,
    approval_required: bool = True,
    idempotency_required: bool = False,
    idempotency_contract_ref: str | None = None,
    readback_deferred_reason: str | None = None,
    requires_human_review: bool = True,
    credential_required: bool = True,
    runtime_bound: bool = False,
) -> VerticalRoleBinding:
    return VerticalRoleBinding(
        action_name=action_name,
        binding_status=RoleBindingStatus.RUNTIME_BOUND if runtime_bound else RoleBindingStatus.CATALOG_ONLY,
        capability_name=capability_name,
        capability_version="1",
        adapter_name=adapter_name,
        adapter_version="1",
        side_effect_class=side_effect_class,
        risk_level=risk_level,
        required_permissions=required_permissions,
        approval_required=approval_required,
        idempotency_required=idempotency_required,
        idempotency_contract_ref=idempotency_contract_ref,
        evidence_required=True,
        evidence_expectations=evidence_expectations,
        readback_required=False,
        readback_deferred_reason=readback_deferred_reason
        or "Deferred until provider activation; no runtime handler bound in Phase A.",
        requires_human_review=requires_human_review,
        enabled_by_default=False,
        credential_required=credential_required,
        deferred_reason=None if runtime_bound else deferred_reason,
    )


# ---------------------------------------------------------------------------
# VERTICAL_OPS_PACK — authoritative Phase A catalog (ADR-0007)
# ---------------------------------------------------------------------------

VERTICAL_OPS_PACK = VerticalRolePack(
    pack_id="vertical_ops.v1",
    version="1.0.0",
    display_name="Vertical Operations Pack v1",
    description=(
        "Declarative catalog of vertical business roles for mission planning. "
        "Does not schedule agents, enqueue work, or grant execution authority."
    ),
    roles=(
        VerticalRoleSpec(
            role_key="vertical.orchestrator",
            display_name="Orchestrator / Planning Lead",
            description="Coordinates mission planning and next-action summaries without autonomous loops.",
            risk_level=AbilityRiskLevel.MEDIUM,
            compliance_category=ComplianceCategory.OPERATIONAL.value,
            default_jurisdiction="US-ALL",
            requires_human_review=False,
            required_permissions=(Permission.MISSION_MANAGE.value, Permission.EXECUTION_VIEW.value),
            evidence_expectations=("plan_id", "summary", "next_actions"),
            enabled_by_default=False,
            notes=(
                "Planning only. Mission plan and task graph materialization use mission_bridge; "
                "this role does not run Celery-style agent loops."
            ),
            bindings=(
                _catalog_only_binding(
                    action_name="vertical.orchestrator.plan",
                    capability_name="vertical_orchestrator",
                    adapter_name="mission-bridge-plan",
                    side_effect_class=SideEffectClass.NONE,
                    risk_level=AbilityRiskLevel.MEDIUM,
                    required_permissions=(Permission.MISSION_MANAGE.value, Permission.EXECUTION_VIEW.value),
                    evidence_expectations=("plan_id", "summary", "next_actions"),
                    deferred_reason=(
                        "Phase A: mission plan templates land in Phase B; no dedicated orchestrator "
                        "action is registered. Use existing mission plan contracts."
                    ),
                    approval_required=False,
                    requires_human_review=False,
                    credential_required=False,
                    readback_deferred_reason="No external write surface for plan-only binding.",
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.planning",
            display_name="Business Planning",
            description="Strategy, KPI recommendations, and growth planning drafts.",
            risk_level=AbilityRiskLevel.MEDIUM,
            compliance_category=ComplianceCategory.OPERATIONAL.value,
            default_jurisdiction="US-ALL",
            requires_human_review=False,
            required_permissions=(Permission.MISSION_MANAGE.value,),
            evidence_expectations=("kpi_updates", "recommendations"),
            enabled_by_default=False,
            notes="Recommendations first; durable KPI writes reuse record/sales write abilities when promoted.",
            bindings=(
                _runtime_binding(
                    action_name="sales.recommend_next_action",
                    capability_name="sales",
                    capability_version="1",
                    adapter_name="local-sales",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.NONE,
                    risk_level=AbilityRiskLevel.LOW,
                    required_permissions=(),
                    approval_required=False,
                    evidence_expectations=("action_result_evidence", "recommendations"),
                ),
                _runtime_binding(
                    action_name="record.write",
                    capability_name="records",
                    capability_version="1",
                    adapter_name="local-records",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.INTERNAL_WRITE,
                    risk_level=AbilityRiskLevel.MEDIUM,
                    required_permissions=(),
                    approval_required=True,
                    evidence_expectations=("action_result_evidence", "kpi_updates"),
                    readback_required=True,
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.research",
            display_name="Competitor Research",
            description="Web and provider-backed research for competitor profiles and sources.",
            risk_level=AbilityRiskLevel.HIGH,
            compliance_category=ComplianceCategory.OPERATIONAL.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.EXECUTION_QUEUE.value,),
            evidence_expectations=("competitor_profiles", "sources"),
            enabled_by_default=False,
            notes="External reads require approval and tenant-visible credentials for provider.external_read.",
            bindings=(
                _runtime_binding(
                    action_name="web.research",
                    capability_name="research",
                    capability_version="1",
                    adapter_name="ajenda-brain",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.INTERNAL_READ,
                    risk_level=AbilityRiskLevel.LOW,
                    required_permissions=(),
                    approval_required=False,
                    evidence_expectations=("action_result_evidence", "sources"),
                ),
                _runtime_binding(
                    action_name="provider.external_read",
                    capability_name="provider_external_read",
                    capability_version="1",
                    adapter_name="external-read-provider",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.EXTERNAL_READ,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(Permission.EXECUTION_QUEUE.value,),
                    approval_required=True,
                    evidence_expectations=("action_result_evidence", "competitor_profiles", "sources"),
                    requires_human_review=True,
                    credential_required=True,
                ),
                _runtime_binding(
                    action_name="sales.research",
                    capability_name="sales",
                    capability_version="1",
                    adapter_name="ajenda-brain",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.INTERNAL_READ,
                    risk_level=AbilityRiskLevel.MEDIUM,
                    required_permissions=(),
                    approval_required=True,
                    evidence_expectations=("action_result_evidence", "sources"),
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.social",
            display_name="Social Media",
            description="Draft and publish social content under governed external_publish gates.",
            risk_level=AbilityRiskLevel.HIGH,
            compliance_category=ComplianceCategory.CONSUMER_INTERACTION.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.EXECUTION_QUEUE.value,),
            evidence_expectations=("post_id", "platform", "content_hash"),
            enabled_by_default=False,
            notes="Drafts use gtm.social_draft; publishing uses existing gtm.social_publish under external_publish gates.",
            bindings=(
                _runtime_binding(
                    action_name="gtm.social_draft",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="local-gtm",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.NONE,
                    risk_level=AbilityRiskLevel.LOW,
                    required_permissions=(),
                    approval_required=False,
                    credential_required=False,
                    requires_human_review=False,
                    evidence_expectations=("action_result_evidence", "platform", "content_hash"),
                ),
                _runtime_binding(
                    action_name="gtm.social_publish",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="external-social",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.EXTERNAL_PUBLISH,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(Permission.EXECUTION_QUEUE.value,),
                    approval_required=True,
                    idempotency_required=True,
                    idempotency_contract_ref=(
                        "docs/product/ability-rollout-contract.md#gtm-social-publish-idempotency"
                    ),
                    evidence_expectations=(
                        "action_result_evidence",
                        "post_id",
                        "platform",
                        "content_hash",
                    ),
                    readback_deferred_reason="External publish proof deferred to platform",
                    requires_human_review=True,
                    credential_required=True,
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.email",
            display_name="Email Outreach",
            description="Draft and send outbound email sequences under external_send gates.",
            risk_level=AbilityRiskLevel.HIGH,
            compliance_category=ComplianceCategory.CONSUMER_INTERACTION.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.EXECUTION_QUEUE.value,),
            evidence_expectations=("sequence_id", "sent_count", "replies"),
            enabled_by_default=False,
            notes="Draft and send map to existing GTM email abilities.",
            bindings=(
                _runtime_binding(
                    action_name="gtm.email_draft",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="local-gtm",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.NONE,
                    risk_level=AbilityRiskLevel.LOW,
                    required_permissions=(),
                    approval_required=False,
                    evidence_expectations=("action_result_evidence",),
                ),
                _runtime_binding(
                    action_name="gtm.email_send",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="external-email",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.EXTERNAL_SEND,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(Permission.EXECUTION_QUEUE.value,),
                    approval_required=True,
                    idempotency_required=True,
                    idempotency_contract_ref=("docs/product/ability-rollout-contract.md#gtm-email-send-idempotency"),
                    evidence_expectations=(
                        "action_result_evidence",
                        "sequence_id",
                        "sent_count",
                    ),
                    readback_deferred_reason="External delivery proof deferred",
                    requires_human_review=True,
                    credential_required=True,
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.support",
            display_name="Customer Support",
            description="Inbox read and reply drafting/sending under consumer-interaction policy.",
            risk_level=AbilityRiskLevel.HIGH,
            compliance_category=ComplianceCategory.CONSUMER_INTERACTION.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.EXECUTION_QUEUE.value,),
            evidence_expectations=("ticket_refs", "reply_count"),
            enabled_by_default=False,
            notes="Reuse GTM email check/draft/send; dedicated support ticket actions remain future work.",
            bindings=(
                _runtime_binding(
                    action_name="gtm.email_check",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="external-email",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.EXTERNAL_READ,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(Permission.EXECUTION_QUEUE.value,),
                    approval_required=True,
                    evidence_expectations=("action_result_evidence", "ticket_refs"),
                    requires_human_review=True,
                    credential_required=True,
                ),
                _runtime_binding(
                    action_name="gtm.email_draft",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="local-gtm",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.NONE,
                    risk_level=AbilityRiskLevel.LOW,
                    required_permissions=(),
                    approval_required=False,
                    evidence_expectations=("action_result_evidence",),
                ),
                _runtime_binding(
                    action_name="gtm.email_send",
                    capability_name="gtm",
                    capability_version="1",
                    adapter_name="external-email",
                    adapter_version="1",
                    side_effect_class=SideEffectClass.EXTERNAL_SEND,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(Permission.EXECUTION_QUEUE.value,),
                    approval_required=True,
                    idempotency_required=True,
                    idempotency_contract_ref=("docs/product/ability-rollout-contract.md#gtm-email-send-idempotency"),
                    evidence_expectations=("action_result_evidence", "reply_count"),
                    readback_deferred_reason="External delivery proof deferred",
                    requires_human_review=True,
                    credential_required=True,
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.ads",
            display_name="Ads Management",
            description="Ad campaign optimization — catalog only until provider proof exists.",
            risk_level=AbilityRiskLevel.CRITICAL,
            compliance_category=ComplianceCategory.FINANCIAL.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.EXECUTION_QUEUE.value, Permission.BILLING_READ.value),
            evidence_expectations=("campaign_updates", "spend_delta"),
            enabled_by_default=False,
            notes="Phase C. No ads provider handler is bound in Phase A.",
            bindings=(
                _catalog_only_binding(
                    action_name="vertical.ads.optimize",
                    capability_name="vertical_ads",
                    adapter_name="ads-provider-deferred",
                    side_effect_class=SideEffectClass.EXTERNAL_WRITE,
                    risk_level=AbilityRiskLevel.CRITICAL,
                    required_permissions=(
                        Permission.EXECUTION_QUEUE.value,
                        Permission.BILLING_READ.value,
                    ),
                    evidence_expectations=("campaign_updates", "spend_delta"),
                    deferred_reason=(
                        "Catalog only until ads provider, credentials, idempotency, and human-review "
                        "proof land (ADR-0007 Phase C)."
                    ),
                    idempotency_required=True,
                    idempotency_contract_ref=("docs/architecture/ADR-0007-governed-vertical-role-catalog.md#phase-c"),
                    requires_human_review=True,
                    credential_required=True,
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.code",
            display_name="Code Generation",
            description="Code change proposals and PR creation — catalog only until Git provider proof.",
            risk_level=AbilityRiskLevel.HIGH,
            compliance_category=ComplianceCategory.OPERATIONAL.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.EXECUTION_QUEUE.value,),
            evidence_expectations=("pr_url", "files_changed", "tests_added"),
            enabled_by_default=False,
            notes="Phase C. No GitHub/PR handler is bound in Phase A.",
            bindings=(
                _catalog_only_binding(
                    action_name="vertical.code.open_pr",
                    capability_name="vertical_code",
                    adapter_name="scm-provider-deferred",
                    side_effect_class=SideEffectClass.EXTERNAL_WRITE,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(Permission.EXECUTION_QUEUE.value,),
                    evidence_expectations=("pr_url", "files_changed", "tests_added"),
                    deferred_reason=(
                        "Catalog only until SCM credentials, PR evidence contract, and idempotency "
                        "proof land (ADR-0007 Phase C)."
                    ),
                    idempotency_required=True,
                    idempotency_contract_ref=("docs/architecture/ADR-0007-governed-vertical-role-catalog.md#phase-c"),
                    requires_human_review=True,
                    credential_required=True,
                ),
            ),
        ),
        VerticalRoleSpec(
            role_key="vertical.finance",
            display_name="Finance",
            description="Revenue sync and financial mutations — mutations catalog only; human review mandatory.",
            risk_level=AbilityRiskLevel.CRITICAL,
            compliance_category=ComplianceCategory.FINANCIAL.value,
            default_jurisdiction="US-ALL",
            requires_human_review=True,
            required_permissions=(Permission.BILLING_MANAGE.value, Permission.EXECUTION_QUEUE.value),
            evidence_expectations=("stripe_events", "revenue_snapshot", "alerts"),
            enabled_by_default=False,
            notes=(
                "Financial risk uses risk_level + ComplianceCategory.FINANCIAL + permissions, "
                "not a fabricated financial_mutation side-effect class."
            ),
            bindings=(
                _catalog_only_binding(
                    action_name="vertical.finance.sync_revenue",
                    capability_name="vertical_finance",
                    adapter_name="billing-sync-deferred",
                    side_effect_class=SideEffectClass.EXTERNAL_READ,
                    risk_level=AbilityRiskLevel.HIGH,
                    required_permissions=(
                        Permission.BILLING_MANAGE.value,
                        Permission.EXECUTION_QUEUE.value,
                    ),
                    evidence_expectations=("stripe_events", "revenue_snapshot"),
                    deferred_reason=(
                        "Catalog only until billing sync action is registered with credentials and "
                        "evidence contracts (ADR-0007 Phase C)."
                    ),
                    approval_required=True,
                    idempotency_required=False,
                    requires_human_review=True,
                    readback_deferred_reason="No write surface for read-sync binding.",
                    runtime_bound=True,
                    credential_required=False,
                ),
                _catalog_only_binding(
                    action_name="vertical.finance.prepare_reconciliation",
                    capability_name="vertical_finance",
                    adapter_name="billing-reconciliation",
                    side_effect_class=SideEffectClass.INTERNAL_READ,
                    risk_level=AbilityRiskLevel.MEDIUM,
                    required_permissions=(Permission.BILLING_MANAGE.value, Permission.EXECUTION_QUEUE.value),
                    evidence_expectations=("stripe_events", "revenue_snapshot"),
                    deferred_reason="Runtime-bound local reconciliation over verified Stripe receipts.",
                    runtime_bound=True,
                    credential_required=False,
                ),
                _catalog_only_binding(
                    action_name="vertical.finance.prepare_invoice_drafts",
                    capability_name="vertical_finance",
                    adapter_name="billing-invoice-drafts",
                    side_effect_class=SideEffectClass.INTERNAL_READ,
                    risk_level=AbilityRiskLevel.MEDIUM,
                    required_permissions=(Permission.BILLING_MANAGE.value, Permission.EXECUTION_QUEUE.value),
                    evidence_expectations=("stripe_events", "revenue_snapshot"),
                    deferred_reason="Runtime-bound draft-only projection; no external send.",
                    runtime_bound=True,
                    credential_required=False,
                ),
                _catalog_only_binding(
                    action_name="vertical.finance.mutate",
                    capability_name="vertical_finance",
                    adapter_name="billing-mutate-deferred",
                    side_effect_class=SideEffectClass.EXTERNAL_WRITE,
                    risk_level=AbilityRiskLevel.CRITICAL,
                    required_permissions=(
                        Permission.BILLING_MANAGE.value,
                        Permission.EXECUTION_QUEUE.value,
                    ),
                    evidence_expectations=("stripe_events", "alerts"),
                    deferred_reason=(
                        "Catalog only. Financial mutations stay disabled until provider, idempotency, "
                        "outcome review, and human-review proof exist (ADR-0007 Phase C)."
                    ),
                    idempotency_required=True,
                    idempotency_contract_ref=("docs/architecture/ADR-0007-governed-vertical-role-catalog.md#phase-c"),
                    requires_human_review=True,
                    credential_required=True,
                ),
            ),
        ),
    ),
)

VERTICAL_ROLE_SPECS_BY_KEY: dict[str, VerticalRoleSpec] = {role.role_key: role for role in VERTICAL_OPS_PACK.roles}
