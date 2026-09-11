"""Vertical mission plan templates (ADR-0007 Phase B + Phase C).

Templates select role bindings from VERTICAL_OPS_PACK and describe mission plan
+ task graph shape. They are declarative planning contracts:

- They do not enqueue work by themselves.
- They do not claim leases or invoke tools.
- Declarative pack/role/template records never grant execution authority.

Phase B: runtime-bound actions present in the ability catalog (research/email/social).
Phase C: catalog-only high-risk roles (ads/code/finance) — plan/graph only until
providers, credentials, idempotency, and human-review proof land.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.abilities.manifest import AbilityRiskLevel
from backend.services.abilities.vertical_role_catalog import (
    VERTICAL_OPS_PACK,
    RoleBindingStatus,
    VerticalRoleBinding,
    get_vertical_role,
)
from backend.services.business_profile_categories import BUSINESS_PROFILE_CATEGORY_FIELDS
from backend.services.tools.schemas import SideEffectClass

PHASE_B_TEMPLATE_IDS: frozenset[str] = frozenset(
    {
        "vertical.research.v1",
        "vertical.email.v1",
        "vertical.social.v1",
        "vertical.finance.v1",
    }
)

PHASE_C_TEMPLATE_IDS: frozenset[str] = frozenset(
    {
        "vertical.ads.v1",
        "vertical.code.v1",
    }
)

KNOWN_TEMPLATE_IDS: frozenset[str] = PHASE_B_TEMPLATE_IDS | PHASE_C_TEMPLATE_IDS


class VerticalTemplateStep(BaseModel):
    """One planned step bound to a role catalog action (runtime or catalog-only)."""

    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1, max_length=120)
    action_name: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1000)
    depends_on: tuple[str, ...] = ()
    include_by_default: bool = True
    optional: bool = False

    @field_validator("step_key", "action_name", "title", "description")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("depends_on")
    @classmethod
    def normalize_depends_on(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("depends_on entries must be non-empty")
            if stripped in normalized:
                raise ValueError("depends_on entries must be unique")
            normalized.append(stripped)
        return tuple(normalized)


class VerticalMissionTemplate(BaseModel):
    """Declarative mission template for one vertical role."""

    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(min_length=1, max_length=160)
    role_key: str = Field(min_length=1, max_length=120)
    pack_id: str = Field(min_length=1, max_length=120)
    pack_version: str = Field(min_length=1, max_length=40)
    display_name: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=1000)
    objective_template: str = Field(min_length=1, max_length=1000)
    steps: tuple[VerticalTemplateStep, ...]
    authority_class: Literal["declarative"] = "declarative"
    grants_execution_authority: Literal[False] = False
    phase: Literal["B", "C"] = "B"
    # Phase C templates are plan/graph only until provider proof exists.
    allows_runtime_queue: bool = True
    required_profile_categories: tuple[str, ...] = ()

    @field_validator(
        "template_id",
        "role_key",
        "pack_id",
        "pack_version",
        "display_name",
        "description",
        "objective_template",
    )
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @model_validator(mode="after")
    def validate_template_against_catalog(self) -> VerticalMissionTemplate:
        if self.template_id not in KNOWN_TEMPLATE_IDS:
            raise ValueError(f"template_id not in known Phase B/C set: {self.template_id}")
        if self.phase == "B" and self.template_id not in PHASE_B_TEMPLATE_IDS:
            raise ValueError(f"phase B template_id invalid: {self.template_id}")
        if self.phase == "C" and self.template_id not in PHASE_C_TEMPLATE_IDS:
            raise ValueError(f"phase C template_id invalid: {self.template_id}")
        if self.grants_execution_authority:
            raise ValueError("templates must not grant execution authority")
        if not self.steps:
            raise ValueError("template requires at least one step")
        if self.phase == "C" and self.allows_runtime_queue:
            raise ValueError("Phase C templates must set allows_runtime_queue=false until providers prove safe")
        if self.phase == "B" and not self.allows_runtime_queue:
            raise ValueError("Phase B templates must allow runtime queue for runtime-bound steps")
        if len(set(self.required_profile_categories)) != len(self.required_profile_categories):
            raise ValueError("required_profile_categories must be unique")
        unknown_categories = set(self.required_profile_categories) - set(BUSINESS_PROFILE_CATEGORY_FIELDS)
        if unknown_categories:
            raise ValueError(f"unknown required profile categories: {sorted(unknown_categories)}")

        step_keys = [step.step_key for step in self.steps]
        if len(step_keys) != len(set(step_keys)):
            raise ValueError("template step_key values must be unique")

        role = get_vertical_role(self.role_key)
        bindings_by_action = {binding.action_name: binding for binding in role.bindings}
        for step in self.steps:
            binding = bindings_by_action.get(step.action_name)
            if binding is None:
                raise ValueError(f"step {step.step_key} action {step.action_name!r} is not on role {self.role_key}")
            if self.allows_runtime_queue:
                if binding.binding_status is not RoleBindingStatus.RUNTIME_BOUND:
                    raise ValueError(
                        f"step {step.step_key} action {step.action_name!r} is not runtime_bound on role {self.role_key}"
                    )
                if step.action_name not in ABILITY_MANIFESTS_BY_ACTION:
                    raise ValueError(f"step {step.step_key} action {step.action_name!r} missing ability manifest")
            else:
                # Plan-only templates may only reference catalog_only bindings.
                if binding.binding_status is not RoleBindingStatus.CATALOG_ONLY:
                    raise ValueError(
                        f"plan-only step {step.step_key} must use catalog_only binding, "
                        f"got {binding.binding_status.value}"
                    )
            for dep in step.depends_on:
                if dep not in step_keys:
                    raise ValueError(f"step {step.step_key} depends_on unknown step_key {dep!r}")
                if dep == step.step_key:
                    raise ValueError(f"step {step.step_key} cannot depend on itself")

        if self.pack_id != VERTICAL_OPS_PACK.pack_id:
            raise ValueError("template pack_id must match VERTICAL_OPS_PACK")
        if self.pack_version != VERTICAL_OPS_PACK.version:
            raise ValueError("template pack_version must match VERTICAL_OPS_PACK")
        return self

    def resolve_binding(self, action_name: str) -> VerticalRoleBinding:
        role = get_vertical_role(self.role_key)
        for binding in role.bindings:
            if binding.action_name == action_name:
                return binding
        raise ValueError(f"binding not found for action {action_name!r} on role {self.role_key}")

    def default_step_keys(self) -> tuple[str, ...]:
        return tuple(step.step_key for step in self.steps if step.include_by_default)

    def selected_steps(self, step_keys: tuple[str, ...] | list[str] | None = None) -> tuple[VerticalTemplateStep, ...]:
        if step_keys is None:
            selected = set(self.default_step_keys())
        else:
            selected = {key.strip() for key in step_keys if key and key.strip()}
            known = {step.step_key for step in self.steps}
            unknown = selected - known
            if unknown:
                raise ValueError(f"unknown template step_keys: {sorted(unknown)}")
        ordered = tuple(step for step in self.steps if step.step_key in selected)
        if not ordered:
            raise ValueError("at least one template step must be selected")
        selected_keys = {step.step_key for step in ordered}
        for step in ordered:
            missing = set(step.depends_on) - selected_keys
            if missing:
                raise ValueError(f"step {step.step_key} selected without required dependencies: {sorted(missing)}")
        return ordered


VERTICAL_MISSION_TEMPLATES: tuple[VerticalMissionTemplate, ...] = (
    # --- Phase B: runtime-capable ---
    VerticalMissionTemplate(
        template_id="vertical.research.v1",
        role_key="vertical.research",
        pack_id=VERTICAL_OPS_PACK.pack_id,
        pack_version=VERTICAL_OPS_PACK.version,
        display_name="Competitor Research Mission",
        description=(
            "Phase B research mission: internal web research first, optional credentialed external read for enrichment."
        ),
        objective_template="Research competitors and capture sources for mission outcomes.",
        required_profile_categories=("company", "market"),
        phase="B",
        allows_runtime_queue=True,
        steps=(
            VerticalTemplateStep(
                step_key="research-internal",
                action_name="web.research",
                title="Internal web research",
                description="Run governed web.research for competitor and market signals.",
                include_by_default=True,
            ),
            VerticalTemplateStep(
                step_key="research-external-read",
                action_name="provider.external_read",
                title="External provider read",
                description="Optional credentialed external read for additional sources.",
                depends_on=("research-internal",),
                include_by_default=False,
                optional=True,
            ),
            VerticalTemplateStep(
                step_key="research-sales",
                action_name="sales.research",
                title="Sales research summary",
                description="Optional sales.research pass over lead/context inputs.",
                depends_on=("research-internal",),
                include_by_default=False,
                optional=True,
            ),
        ),
    ),
    VerticalMissionTemplate(
        template_id="vertical.email.v1",
        role_key="vertical.email",
        pack_id=VERTICAL_OPS_PACK.pack_id,
        pack_version=VERTICAL_OPS_PACK.version,
        display_name="Email Outreach Mission",
        description=(
            "Phase B email mission: draft first (no side effect), optional governed send "
            "behind existing GTM high-risk gates."
        ),
        objective_template="Prepare and optionally send governed outreach email.",
        required_profile_categories=("company", "market", "growth"),
        phase="B",
        allows_runtime_queue=True,
        steps=(
            VerticalTemplateStep(
                step_key="email-draft",
                action_name="gtm.email_draft",
                title="Draft outreach email",
                description="Generate draft email content without sending.",
                include_by_default=True,
            ),
            VerticalTemplateStep(
                step_key="email-send",
                action_name="gtm.email_send",
                title="Send outreach email",
                description="Governed external_send via gtm.email_send with credentials and idempotency.",
                depends_on=("email-draft",),
                include_by_default=False,
                optional=True,
            ),
        ),
    ),
    VerticalMissionTemplate(
        template_id="vertical.social.v1",
        role_key="vertical.social",
        pack_id=VERTICAL_OPS_PACK.pack_id,
        pack_version=VERTICAL_OPS_PACK.version,
        display_name="Social Publish Mission",
        description=("Phase B social mission bound to existing gtm.social_publish under external_publish gates."),
        objective_template="Publish social content under governed external_publish authority.",
        required_profile_categories=("company", "growth"),
        phase="B",
        allows_runtime_queue=True,
        steps=(
            VerticalTemplateStep(
                step_key="social-publish",
                action_name="gtm.social_publish",
                title="Publish social content",
                description="Governed external_publish via gtm.social_publish.",
                include_by_default=True,
            ),
        ),
    ),
    # --- Phase C: plan-only high risk (no runtime queue) ---
    VerticalMissionTemplate(
        template_id="vertical.ads.v1",
        role_key="vertical.ads",
        pack_id=VERTICAL_OPS_PACK.pack_id,
        pack_version=VERTICAL_OPS_PACK.version,
        display_name="Ads Management Mission (plan-only)",
        description=(
            "Phase C ads mission: catalog-only until ads provider, credentials, idempotency, "
            "and human-review proof exist. Runtime queue is disabled."
        ),
        objective_template="Plan governed ad optimization work without executing provider mutations.",
        required_profile_categories=("growth", "metrics"),
        phase="C",
        allows_runtime_queue=False,
        steps=(
            VerticalTemplateStep(
                step_key="ads-optimize",
                action_name="vertical.ads.optimize",
                title="Optimize ad campaigns",
                description="Deferred catalog-only ads optimization action.",
                include_by_default=True,
            ),
        ),
    ),
    VerticalMissionTemplate(
        template_id="vertical.code.v1",
        role_key="vertical.code",
        pack_id=VERTICAL_OPS_PACK.pack_id,
        pack_version=VERTICAL_OPS_PACK.version,
        display_name="Code Generation Mission (plan-only)",
        description=(
            "Phase C code mission: catalog-only until SCM credentials, PR evidence, and "
            "idempotency proof exist. Runtime queue is disabled."
        ),
        objective_template="Plan governed code/PR work without opening PRs.",
        required_profile_categories=("company", "delivery"),
        phase="C",
        allows_runtime_queue=False,
        steps=(
            VerticalTemplateStep(
                step_key="code-open-pr",
                action_name="vertical.code.open_pr",
                title="Open pull request",
                description="Deferred catalog-only SCM PR action.",
                include_by_default=True,
            ),
        ),
    ),
    VerticalMissionTemplate(
        template_id="vertical.finance.v1",
        role_key="vertical.finance",
        pack_id=VERTICAL_OPS_PACK.pack_id,
        pack_version=VERTICAL_OPS_PACK.version,
        display_name="Finance Mission",
        description=(
            "Phase C finance mission: catalog-only revenue sync and mutations until billing "
            "provider proof exists. Runtime queue is disabled. Financial risk uses "
            "risk_level + ComplianceCategory.FINANCIAL, not a fake side-effect class."
        ),
        objective_template="Plan governed finance sync/mutation work without executing mutations.",
        required_profile_categories=("company", "metrics"),
        phase="B",
        allows_runtime_queue=True,
        steps=(
            VerticalTemplateStep(
                step_key="finance-sync",
                action_name="vertical.finance.sync_revenue",
                title="Sync revenue snapshot",
                description="Deferred catalog-only billing sync action.",
                include_by_default=True,
            ),
        ),
    ),
)

VERTICAL_MISSION_TEMPLATES_BY_ID: dict[str, VerticalMissionTemplate] = {
    template.template_id: template for template in VERTICAL_MISSION_TEMPLATES
}


def get_vertical_mission_template(template_id: str) -> VerticalMissionTemplate:
    """Return a Phase B or Phase C template by id."""

    template = VERTICAL_MISSION_TEMPLATES_BY_ID.get(template_id.strip())
    if template is None:
        raise ValueError(f"unknown vertical mission template: {template_id}")
    return template


def list_vertical_mission_templates(
    *,
    phase: Literal["B", "C"] | None = None,
    queueable_only: bool = False,
) -> tuple[VerticalMissionTemplate, ...]:
    """Return vertical mission templates, optionally filtered."""

    templates = VERTICAL_MISSION_TEMPLATES
    if phase is not None:
        templates = tuple(item for item in templates if item.phase == phase)
    if queueable_only:
        templates = tuple(item for item in templates if item.allows_runtime_queue)
    return templates


def template_step_side_effect(action_name: str, *, role_key: str | None = None) -> SideEffectClass:
    """Resolve side-effect class from ability catalog or role binding."""

    manifest = ABILITY_MANIFESTS_BY_ACTION.get(action_name)
    if manifest is not None:
        return manifest.side_effect_class
    if role_key is None:
        raise ValueError(f"unknown action for side-effect resolution: {action_name}")
    role = get_vertical_role(role_key)
    for binding in role.bindings:
        if binding.action_name == action_name:
            return binding.side_effect_class
    raise ValueError(f"unknown action for side-effect resolution: {action_name}")


def template_step_risk(action_name: str, *, role_key: str | None = None) -> AbilityRiskLevel:
    """Resolve risk level from ability catalog or role binding."""

    manifest = ABILITY_MANIFESTS_BY_ACTION.get(action_name)
    if manifest is not None:
        return manifest.risk_level
    if role_key is None:
        raise ValueError(f"unknown action for risk resolution: {action_name}")
    role = get_vertical_role(role_key)
    for binding in role.bindings:
        if binding.action_name == action_name:
            return binding.risk_level
    raise ValueError(f"unknown action for risk resolution: {action_name}")
