from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.domain.business_profile import BusinessProfile
from backend.domain.compliance import is_supported_compliance_category, is_supported_jurisdiction

MISSION_BRIEF_SCHEMA_VERSION = 1
MAX_MISSION_BRIEF_JSON_BYTES = 24_576
MAX_MISSION_BRIEF_JSON_DEPTH = 8
MAX_MISSION_BRIEF_JSON_KEYS = 192
MISSION_CREATE_MAX_SUCCESS_CRITERIA = 20
MISSION_CREATE_MAX_CONSTRAINTS = 20
MISSION_CREATE_MAX_DESCRIPTION_LENGTH = 1000
MISSION_CREATE_MAX_POLICY_FIELD_LENGTH = 64
MISSION_CREATE_MAX_CONSTRAINT_NAME_LENGTH = 120
MISSION_CREATE_MAX_EVIDENCE_ITEMS = 10
MISSION_CREATE_MAX_APPROVAL_EXPECTATIONS = 20
MISSION_CREATE_MAX_SCOPE_LIMITS = 20
MISSION_CREATE_MAX_ALLOWED_ACTIONS = 50
MISSION_CREATE_MAX_ALLOWED_TOOLS = 50
MISSION_BRIEF_MAX_LIST_ITEM_LENGTH = 1000
MISSION_BRIEF_MAX_PROFILE_CONTEXT_ITEMS = 50
MissionBriefSource = Literal["current_intent", "business_profile", "request_context", "system_default"]


def _validate_json_payload(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    def _walk(node: Any, *, depth: int, key_count: list[int]) -> None:
        if depth > MAX_MISSION_BRIEF_JSON_DEPTH:
            raise ValueError(f"{field_name} exceeds maximum JSON depth")
        if isinstance(node, dict):
            key_count[0] += len(node)
            if key_count[0] > MAX_MISSION_BRIEF_JSON_KEYS:
                raise ValueError(f"{field_name} exceeds maximum JSON key count")
            for key, child in node.items():
                if not isinstance(key, str):
                    raise ValueError(f"{field_name} JSON object keys must be strings")
                _walk(child, depth=depth + 1, key_count=key_count)
            return
        if isinstance(node, list):
            for child in node:
                _walk(child, depth=depth + 1, key_count=key_count)
            return
        if node is not None and not isinstance(node, str | int | float | bool):
            raise ValueError(f"{field_name} contains a non-JSON value")

    _walk(value, depth=1, key_count=[0])
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_MISSION_BRIEF_JSON_BYTES:
        raise ValueError(f"{field_name} exceeds maximum JSON size")
    return value


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _clean_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values: list[Any] = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    normalized: list[str] = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = _clean_text(item.get("description") or item.get("name") or item.get("value")) or ""
        else:
            text = ""
        if (
            text
            and len(text) <= MISSION_BRIEF_MAX_LIST_ITEM_LENGTH
            and text not in normalized
            and len(normalized) < MISSION_BRIEF_MAX_PROFILE_CONTEXT_ITEMS
        ):
            normalized.append(text)
    return normalized


def _profile_text(
    profile_facts: dict[str, Any],
    *keys: str,
    max_length: int = MISSION_BRIEF_MAX_LIST_ITEM_LENGTH,
) -> tuple[str | None, str | None]:
    for key in keys:
        value = profile_facts.get(key)
        if isinstance(value, str):
            text = _clean_text(value)
            if text and len(text) <= max_length:
                return text, key
        if isinstance(value, dict):
            text = _clean_text(value.get("value") or value.get("default") or value.get("name"))
            if text and len(text) <= max_length:
                return text, key
    return None, None


def _profile_list(profile_facts: dict[str, Any], *keys: str) -> tuple[list[str], str | None]:
    for key in keys:
        value = profile_facts.get(key)
        values: list[str] = []
        if isinstance(value, dict):
            for nested_key in ("values", "items", "defaults", "allowed", "expectations", "segments", "services"):
                values = _clean_text_list(value.get(nested_key))
                if values:
                    return values, key
            values = _clean_text_list(value.get("value"))
        else:
            values = _clean_text_list(value)
        if values:
            return values, key
    return [], None


def _profile_bool(profile_facts: dict[str, Any], *keys: str) -> tuple[bool | None, str | None]:
    for key in keys:
        value = profile_facts.get(key)
        if isinstance(value, bool):
            return value, key
        if isinstance(value, dict) and isinstance(value.get("value"), bool):
            return value["value"], key
        if isinstance(value, dict) and isinstance(value.get("required"), bool):
            return value["required"], key
    return None, None


def _is_valid_budget_limits(value: dict[str, Any]) -> bool:
    if not value:
        return False
    for key in ("max_tasks", "max_runtime_minutes"):
        if key in value and (not isinstance(value[key], int) or value[key] < 1):
            return False
    if "max_cost_usd" in value and (not isinstance(value["max_cost_usd"], int | float) or value["max_cost_usd"] <= 0):
        return False
    return True


def _profile_budget(profile_facts: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    for key in ("budget_limits", "default_budget_limits", "budget", "default_budget"):
        value = profile_facts.get(key)
        if isinstance(value, dict):
            budget = {k: v for k, v in value.items() if k in {"max_tasks", "max_runtime_minutes", "max_cost_usd"}}
            if _is_valid_budget_limits(budget):
                return budget, key
    return None, None


def _merge_lists(*, explicit: list[str], profile_values: list[str], max_items: int) -> list[str]:
    merged: list[str] = []
    for item in [*explicit, *profile_values]:
        text = item.strip()
        if not text or len(text) > MISSION_BRIEF_MAX_LIST_ITEM_LENGTH or text in merged:
            continue
        if len(merged) >= max_items:
            break
        merged.append(text)
    return merged


class MissionBriefIntent(BaseModel):
    """Mission-specific intent used only to draft a read-only Mission Brief."""

    model_config = ConfigDict(extra="forbid")

    objective: str | None = Field(default=None, max_length=5000)
    success_criteria: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    operator_notes: str | None = Field(default=None, max_length=5000)
    context: dict[str, Any] = Field(default_factory=dict)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    approval_required: bool | None = None
    approval_expectations: list[str] = Field(default_factory=list, max_length=20)
    budget_limits: dict[str, Any] | None = None
    scope_limits: list[str] = Field(default_factory=list, max_length=20)
    allowed_actions: list[str] = Field(default_factory=list, max_length=50)
    allowed_tools: list[str] = Field(default_factory=list, max_length=50)
    evidence_expectations: list[str] = Field(default_factory=list, max_length=20)
    compliance_category: str | None = Field(default=None, max_length=64)
    jurisdiction: str | None = Field(default=None, max_length=64)

    @field_validator("objective", "operator_notes", "compliance_category", "jurisdiction")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("text fields must be non-empty when provided")
        return value

    @field_validator(
        "success_criteria",
        "constraints",
        "approval_expectations",
        "scope_limits",
        "allowed_actions",
        "allowed_tools",
        "evidence_expectations",
    )
    @classmethod
    def _normalize_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("list entries must be non-empty strings")
        if any(len(item) > MISSION_BRIEF_MAX_LIST_ITEM_LENGTH for item in normalized):
            raise ValueError(f"list entries must be at most {MISSION_BRIEF_MAX_LIST_ITEM_LENGTH} characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("list entries must be unique")
        return normalized

    @field_validator("context")
    @classmethod
    def _validate_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_payload(value, field_name="context")

    @field_validator("budget_limits")
    @classmethod
    def _validate_budget_limits(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        _validate_json_payload(value, field_name="budget_limits")
        allowed = {"max_tasks", "max_runtime_minutes", "max_cost_usd"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("budget_limits contains unsupported keys")
        for key in ("max_tasks", "max_runtime_minutes"):
            if key in value and (not isinstance(value[key], int) or value[key] < 1):
                raise ValueError(f"{key} must be a positive integer")
        if "max_cost_usd" in value and (
            not isinstance(value["max_cost_usd"], int | float) or value["max_cost_usd"] <= 0
        ):
            raise ValueError("max_cost_usd must be a positive number")
        if not _is_valid_budget_limits(value):
            raise ValueError("budget_limits must include at least one valid positive limit when provided")
        return value

    @field_validator("compliance_category")
    @classmethod
    def _validate_compliance_category(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_compliance_category(value):
            raise ValueError("unsupported compliance_category")
        return value

    @field_validator("jurisdiction")
    @classmethod
    def _validate_jurisdiction(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_jurisdiction(value):
            raise ValueError("unsupported jurisdiction")
        return value


class MissionBriefRequest(BaseModel):
    """Read-model request; validation is bounded and creates no mission/runtime state."""

    model_config = ConfigDict(extra="forbid")

    current_intent: MissionBriefIntent
    request_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_context")
    @classmethod
    def _validate_request_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_payload(value, field_name="request_context")


class MissionBriefMissingInformation(BaseModel):
    field: str
    reason: str
    severity: Literal["required", "recommended"]


class MissionBriefProvenance(BaseModel):
    field: str
    source: MissionBriefSource
    profile_category: str | None = None
    note: str | None = None


class MissionBriefConflict(BaseModel):
    field: str
    current_intent: Any
    business_profile_default: Any
    resolution: Literal["current_intent_wins", "clarification_recommended"]


class MissionBriefAuthorityFlags(BaseModel):
    authority_class: Literal["read_model"] = "read_model"
    read_only: Literal[True] = True
    creates_mission: Literal[False] = False
    creates_mission_plan: Literal[False] = False
    creates_task_graph: Literal[False] = False
    creates_execution_tasks: Literal[False] = False
    queues_work: Literal[False] = False
    dispatches_workers: Literal[False] = False
    mutates_worker_leases: Literal[False] = False
    writes_business_profile_truth: Literal[False] = False
    promotes_memory: Literal[False] = False
    bypasses_authority_checks: Literal[False] = False


def _prefill_missing_information(
    *,
    missing: list[MissionBriefMissingInformation],
    field: str,
    reason: str,
    severity: Literal["required", "recommended"] = "recommended",
) -> None:
    missing.append(MissionBriefMissingInformation(field=field, reason=reason, severity=severity))


def _mission_create_text_values(
    *,
    values: list[str],
    field: str,
    max_items: int,
    missing: list[MissionBriefMissingInformation],
    max_length: int | None = None,
) -> list[str]:
    """Return values that are safe to copy into MissionCreate list fields."""
    accepted: list[str] = []
    omitted_for_length = 0
    omitted_for_count = 0
    for value in values:
        text = value.strip()
        if not text:
            continue
        if max_length is not None and len(text) > max_length:
            omitted_for_length += 1
            continue
        if text in accepted:
            continue
        if len(accepted) >= max_items:
            omitted_for_count += 1
            continue
        accepted.append(text)

    if omitted_for_length:
        _prefill_missing_information(
            missing=missing,
            field=field,
            reason=(
                f"{omitted_for_length} value(s) were omitted from MissionCreate prefill because they exceed "
                f"the {max_length}-character MissionCreate limit."
            ),
        )
    if omitted_for_count:
        _prefill_missing_information(
            missing=missing,
            field=field,
            reason=(
                f"{omitted_for_count} value(s) were omitted from MissionCreate prefill because MissionCreate "
                f"accepts at most {max_items} item(s) for this field."
            ),
        )
    return accepted


def _mission_create_success_criteria(
    *,
    success_criteria: list[str],
    evidence_expectations: list[str],
    missing: list[MissionBriefMissingInformation],
) -> list[dict[str, Any]]:
    prefill_success_criteria = _mission_create_text_values(
        values=success_criteria,
        field="success_criteria",
        max_items=MISSION_CREATE_MAX_SUCCESS_CRITERIA,
        max_length=MISSION_CREATE_MAX_DESCRIPTION_LENGTH,
        missing=missing,
    )
    prefill_evidence = _mission_create_text_values(
        values=evidence_expectations,
        field="success_criteria.evidence",
        max_items=MISSION_CREATE_MAX_EVIDENCE_ITEMS,
        missing=missing,
    )
    return [{"description": criterion, "evidence": prefill_evidence} for criterion in prefill_success_criteria]


def _mission_create_constraints(
    *, constraints: list[str], missing: list[MissionBriefMissingInformation]
) -> list[dict[str, Any]]:
    prefill_constraints = _mission_create_text_values(
        values=constraints,
        field="constraints",
        max_items=MISSION_CREATE_MAX_CONSTRAINTS,
        max_length=MISSION_CREATE_MAX_DESCRIPTION_LENGTH,
        missing=missing,
    )
    return [
        {
            "name": item[:MISSION_CREATE_MAX_CONSTRAINT_NAME_LENGTH],
            "description": item,
            "hard": True,
        }
        for item in prefill_constraints
    ]


class MissionBriefReadiness(BaseModel):
    """Deterministic readiness summary for explicit MissionCreate review."""

    state: Literal["ready", "blocked"]
    ready_for_mission_create: bool
    blocking_fields: list[str]
    recommendations: list[str]


class MissionBriefRead(BaseModel):
    schema_version: int
    tenant_id: str
    profile_id: UUID | None
    brief: dict[str, Any]
    missing_information: list[MissionBriefMissingInformation]
    mission_create_prefill: dict[str, Any]
    readiness: MissionBriefReadiness
    provenance: list[MissionBriefProvenance]
    conflicts: list[MissionBriefConflict]
    authority_flags: MissionBriefAuthorityFlags

    @model_validator(mode="after")
    def _assert_read_model_flags(self) -> MissionBriefRead:
        if self.authority_flags.authority_class != "read_model" or not self.authority_flags.read_only:
            raise ValueError("Mission Brief must remain a read-only read model")
        return self


def build_mission_brief(
    *, tenant_id: str, profile: BusinessProfile | None, request: MissionBriefRequest
) -> MissionBriefRead:
    """Build a deterministic Mission Brief read model without persistence or runtime authority."""
    profile_facts = profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
    intent = request.current_intent
    provenance: list[MissionBriefProvenance] = []
    conflicts: list[MissionBriefConflict] = []

    objective = intent.objective
    if objective:
        provenance.append(MissionBriefProvenance(field="objective", source="current_intent"))

    success_profile, success_key = _profile_list(profile_facts, "success_criteria", "default_success_criteria")
    success_criteria = _merge_lists(
        explicit=intent.success_criteria, profile_values=success_profile, max_items=MISSION_CREATE_MAX_SUCCESS_CRITERIA
    )
    if intent.success_criteria:
        provenance.append(MissionBriefProvenance(field="success_criteria", source="current_intent"))
    if success_profile:
        provenance.append(
            MissionBriefProvenance(field="success_criteria", source="business_profile", profile_category=success_key)
        )

    evidence_profile, evidence_key = _profile_list(
        profile_facts, "evidence_expectations", "default_evidence_expectations"
    )
    evidence_expectations = _merge_lists(
        explicit=intent.evidence_expectations,
        profile_values=evidence_profile,
        max_items=MISSION_CREATE_MAX_EVIDENCE_ITEMS,
    )
    if intent.evidence_expectations:
        provenance.append(MissionBriefProvenance(field="evidence_expectations", source="current_intent"))
    if evidence_profile:
        provenance.append(
            MissionBriefProvenance(
                field="evidence_expectations", source="business_profile", profile_category=evidence_key
            )
        )

    constraint_profile, constraint_key = _profile_list(
        profile_facts, "constraints", "default_constraints", "operating_constraints"
    )
    constraints = _merge_lists(
        explicit=intent.constraints, profile_values=constraint_profile, max_items=MISSION_CREATE_MAX_CONSTRAINTS
    )
    if intent.constraints:
        provenance.append(MissionBriefProvenance(field="constraints", source="current_intent"))
    if constraint_profile:
        provenance.append(
            MissionBriefProvenance(field="constraints", source="business_profile", profile_category=constraint_key)
        )

    allowed_action_profile, allowed_action_key = _profile_list(
        profile_facts, "allowed_actions", "default_allowed_actions"
    )
    allowed_actions = _merge_lists(
        explicit=intent.allowed_actions,
        profile_values=allowed_action_profile,
        max_items=MISSION_CREATE_MAX_ALLOWED_ACTIONS,
    )
    if intent.allowed_actions:
        provenance.append(MissionBriefProvenance(field="allowed_actions", source="current_intent"))
    if allowed_action_profile:
        provenance.append(
            MissionBriefProvenance(
                field="allowed_actions", source="business_profile", profile_category=allowed_action_key
            )
        )

    allowed_tool_profile, allowed_tool_key = _profile_list(profile_facts, "allowed_tools", "default_allowed_tools")
    allowed_tools = _merge_lists(
        explicit=intent.allowed_tools, profile_values=allowed_tool_profile, max_items=MISSION_CREATE_MAX_ALLOWED_TOOLS
    )
    if intent.allowed_tools:
        provenance.append(MissionBriefProvenance(field="allowed_tools", source="current_intent"))
    if allowed_tool_profile:
        provenance.append(
            MissionBriefProvenance(field="allowed_tools", source="business_profile", profile_category=allowed_tool_key)
        )

    scope_profile, scope_key = _profile_list(profile_facts, "scope_limits", "default_scope", "default_scope_limits")
    scope_limits = _merge_lists(
        explicit=intent.scope_limits, profile_values=scope_profile, max_items=MISSION_CREATE_MAX_SCOPE_LIMITS
    )
    if intent.scope_limits:
        provenance.append(MissionBriefProvenance(field="scope_limits", source="current_intent"))
    if scope_profile:
        provenance.append(
            MissionBriefProvenance(field="scope_limits", source="business_profile", profile_category=scope_key)
        )

    approval_expectations_profile, approval_expectations_key = _profile_list(
        profile_facts, "approval_expectations", "approval_rules", "default_approval_expectations"
    )
    approval_expectations = _merge_lists(
        explicit=intent.approval_expectations,
        profile_values=approval_expectations_profile,
        max_items=MISSION_CREATE_MAX_APPROVAL_EXPECTATIONS,
    )
    if intent.approval_expectations:
        provenance.append(MissionBriefProvenance(field="approval_expectations", source="current_intent"))
    if approval_expectations_profile:
        provenance.append(
            MissionBriefProvenance(
                field="approval_expectations", source="business_profile", profile_category=approval_expectations_key
            )
        )

    approval_required_profile, approval_required_key = _profile_bool(
        profile_facts, "approval_required", "default_approval_required"
    )
    approval_required = (
        intent.approval_required if intent.approval_required is not None else approval_required_profile or False
    )
    if intent.approval_required is not None:
        provenance.append(MissionBriefProvenance(field="approval_required", source="current_intent"))
        if approval_required_profile is not None and approval_required_profile != intent.approval_required:
            conflicts.append(
                MissionBriefConflict(
                    field="approval_required",
                    current_intent=intent.approval_required,
                    business_profile_default=approval_required_profile,
                    resolution="current_intent_wins",
                )
            )
    elif approval_required_profile is not None:
        provenance.append(
            MissionBriefProvenance(
                field="approval_required", source="business_profile", profile_category=approval_required_key
            )
        )

    profile_budget, budget_key = _profile_budget(profile_facts)
    budget_limits = intent.budget_limits if intent.budget_limits is not None else profile_budget
    if intent.budget_limits is not None:
        provenance.append(MissionBriefProvenance(field="budget_limits", source="current_intent"))
        if profile_budget is not None and profile_budget != intent.budget_limits:
            conflicts.append(
                MissionBriefConflict(
                    field="budget_limits",
                    current_intent=intent.budget_limits,
                    business_profile_default=profile_budget,
                    resolution="current_intent_wins",
                )
            )
    elif profile_budget is not None:
        provenance.append(
            MissionBriefProvenance(field="budget_limits", source="business_profile", profile_category=budget_key)
        )

    profile_compliance, compliance_key = _profile_text(
        profile_facts,
        "compliance_category",
        "default_compliance_category",
        max_length=MISSION_CREATE_MAX_POLICY_FIELD_LENGTH,
    )
    compliance_category = intent.compliance_category or (profile_compliance if profile_compliance else "operational")
    if not is_supported_compliance_category(compliance_category):
        conflicts.append(
            MissionBriefConflict(
                field="compliance_category",
                current_intent=intent.compliance_category,
                business_profile_default=profile_compliance,
                resolution="clarification_recommended",
            )
        )
        compliance_category = intent.compliance_category or "operational"
    if intent.compliance_category:
        provenance.append(MissionBriefProvenance(field="compliance_category", source="current_intent"))
        if profile_compliance and profile_compliance != intent.compliance_category:
            conflicts.append(
                MissionBriefConflict(
                    field="compliance_category",
                    current_intent=intent.compliance_category,
                    business_profile_default=profile_compliance,
                    resolution="current_intent_wins",
                )
            )
    elif profile_compliance:
        provenance.append(
            MissionBriefProvenance(
                field="compliance_category", source="business_profile", profile_category=compliance_key
            )
        )
    else:
        provenance.append(MissionBriefProvenance(field="compliance_category", source="system_default"))

    profile_jurisdiction, jurisdiction_key = _profile_text(
        profile_facts, "jurisdiction", "default_jurisdiction", max_length=MISSION_CREATE_MAX_POLICY_FIELD_LENGTH
    )
    jurisdiction = intent.jurisdiction or (profile_jurisdiction if profile_jurisdiction else "US-ALL")
    if not is_supported_jurisdiction(jurisdiction):
        conflicts.append(
            MissionBriefConflict(
                field="jurisdiction",
                current_intent=intent.jurisdiction,
                business_profile_default=profile_jurisdiction,
                resolution="clarification_recommended",
            )
        )
        jurisdiction = intent.jurisdiction or "US-ALL"
    if intent.jurisdiction:
        provenance.append(MissionBriefProvenance(field="jurisdiction", source="current_intent"))
        if profile_jurisdiction and profile_jurisdiction != intent.jurisdiction:
            conflicts.append(
                MissionBriefConflict(
                    field="jurisdiction",
                    current_intent=intent.jurisdiction,
                    business_profile_default=profile_jurisdiction,
                    resolution="current_intent_wins",
                )
            )
    elif profile_jurisdiction:
        provenance.append(
            MissionBriefProvenance(field="jurisdiction", source="business_profile", profile_category=jurisdiction_key)
        )
    else:
        provenance.append(MissionBriefProvenance(field="jurisdiction", source="system_default"))

    business_name, business_name_key = _profile_text(profile_facts, "business_name", "name")
    target_customers, target_customers_key = _profile_list(profile_facts, "target_customers", "customer_segments")
    products_services, products_services_key = _profile_list(
        profile_facts, "products_services", "services", "offerings"
    )
    profile_context: dict[str, Any] = {}
    if business_name:
        profile_context["business_name"] = business_name
        provenance.append(
            MissionBriefProvenance(
                field="profile_context.business_name", source="business_profile", profile_category=business_name_key
            )
        )
    if target_customers:
        profile_context["target_customers"] = target_customers
        provenance.append(
            MissionBriefProvenance(
                field="profile_context.target_customers",
                source="business_profile",
                profile_category=target_customers_key,
            )
        )
    if products_services:
        profile_context["products_services"] = products_services
        provenance.append(
            MissionBriefProvenance(
                field="profile_context.products_services",
                source="business_profile",
                profile_category=products_services_key,
            )
        )

    missing: list[MissionBriefMissingInformation] = []
    mission_create_success_criteria = _mission_create_success_criteria(
        success_criteria=success_criteria,
        evidence_expectations=evidence_expectations,
        missing=missing,
    )
    mission_create_constraints = _mission_create_constraints(constraints=constraints, missing=missing)
    mission_create_approval_expectations = _mission_create_text_values(
        values=approval_expectations,
        field="approval_expectations",
        max_items=MISSION_CREATE_MAX_APPROVAL_EXPECTATIONS,
        missing=missing,
    )
    mission_create_scope_limits = _mission_create_text_values(
        values=scope_limits,
        field="scope_limits",
        max_items=MISSION_CREATE_MAX_SCOPE_LIMITS,
        missing=missing,
    )
    mission_create_allowed_actions = _mission_create_text_values(
        values=allowed_actions,
        field="allowed_actions",
        max_items=MISSION_CREATE_MAX_ALLOWED_ACTIONS,
        missing=missing,
    )
    mission_create_allowed_tools = _mission_create_text_values(
        values=allowed_tools,
        field="allowed_tools",
        max_items=MISSION_CREATE_MAX_ALLOWED_TOOLS,
        missing=missing,
    )

    if not objective:
        _prefill_missing_information(
            missing=missing,
            field="objective",
            reason="Current mission objective is required before MissionCreate.",
            severity="required",
        )
    if not mission_create_success_criteria:
        _prefill_missing_information(
            missing=missing,
            field="success_criteria",
            reason="At least one MissionCreate-valid measurable success criterion is required before MissionCreate.",
            severity="required",
        )
    if not evidence_expectations:
        _prefill_missing_information(
            missing=missing,
            field="evidence_expectations",
            reason="Evidence expectations are recommended so mission outputs can be reviewed.",
        )

    context = dict(intent.context)
    if request.request_context:
        context["request_context"] = request.request_context
        provenance.append(MissionBriefProvenance(field="context.request_context", source="request_context"))
    if profile_context:
        context["business_profile"] = profile_context

    mission_create_prefill: dict[str, Any] = {
        "objective": objective,
        "success_criteria": mission_create_success_criteria,
        "constraints": mission_create_constraints,
        "operator_notes": intent.operator_notes,
        "context": context,
        "priority": intent.priority or "normal",
        "approval_required": approval_required,
        "approval_expectations": mission_create_approval_expectations,
        "budget_limits": budget_limits,
        "scope_limits": mission_create_scope_limits,
        "allowed_actions": mission_create_allowed_actions,
        "allowed_tools": mission_create_allowed_tools,
        "compliance_category": compliance_category,
        "jurisdiction": jurisdiction,
    }
    mission_create_prefill = {
        key: value for key, value in mission_create_prefill.items() if value not in (None, [], {})
    }

    brief = {
        "objective": objective,
        "success_criteria": success_criteria,
        "constraints": constraints,
        "evidence_expectations": evidence_expectations,
        "allowed_actions": allowed_actions,
        "allowed_tools": allowed_tools,
        "approval_required": approval_required,
        "approval_expectations": approval_expectations,
        "scope_limits": scope_limits,
        "budget_limits": budget_limits,
        "compliance_category": compliance_category,
        "jurisdiction": jurisdiction,
        "profile_context": profile_context,
        "current_intent_wins_over_profile_defaults": True,
    }
    brief = {key: value for key, value in brief.items() if value not in (None, [], {})}

    blocking_fields = list(
        dict.fromkeys(item.field for item in missing if item.severity == "required")
    )
    recommendations = list(
        dict.fromkeys(item.field for item in missing if item.severity == "recommended")
    )
    readiness = MissionBriefReadiness(
        state="blocked" if blocking_fields else "ready",
        ready_for_mission_create=not blocking_fields,
        blocking_fields=blocking_fields,
        recommendations=recommendations,
    )

    return MissionBriefRead(
        schema_version=MISSION_BRIEF_SCHEMA_VERSION,
        tenant_id=tenant_id,
        profile_id=profile.id if profile is not None else None,
        brief=brief,
        missing_information=missing,
        mission_create_prefill=mission_create_prefill,
        readiness=readiness,
        provenance=provenance,
        conflicts=conflicts,
        authority_flags=MissionBriefAuthorityFlags(),
    )
