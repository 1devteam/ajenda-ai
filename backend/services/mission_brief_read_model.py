from __future__ import annotations

from copy import deepcopy
from typing import Any

MISSION_BRIEF_SCHEMA_VERSION = 1

MISSION_CREATE_FIELDS: tuple[str, ...] = (
    "objective",
    "success_criteria",
    "constraints",
    "operator_notes",
    "context",
    "priority",
    "approval_required",
    "approval_expectations",
    "budget_limits",
    "scope_limits",
    "allowed_actions",
    "allowed_tools",
    "compliance_category",
    "jurisdiction",
)

PROFILE_DEFAULT_FIELD_CATEGORIES: dict[str, tuple[str, ...]] = {
    "allowed_actions": ("allowed_actions", "default_allowed_actions"),
    "allowed_tools": ("allowed_tools", "default_allowed_tools"),
    "approval_required": ("approval_required", "default_approval_required"),
    "approval_expectations": ("approval_expectations", "approval_rules", "approval_requirements"),
    "budget_limits": ("budget_limits", "default_budget", "default_budget_limits"),
    "scope_limits": ("scope_limits", "default_scope", "default_scope_limits"),
    "compliance_category": ("compliance_category", "default_compliance", "default_compliance_category"),
    "jurisdiction": ("jurisdiction", "default_jurisdiction"),
}

PROFILE_CONTEXT_CATEGORIES: tuple[str, ...] = (
    "business_name",
    "business_type",
    "industry",
    "service_area",
    "service_areas",
    "operating_regions",
    "products",
    "services",
    "offerings",
    "target_customers",
    "customer_segments",
    "team_roles",
    "worker_responsibilities",
    "evidence_expectations",
)

MISSION_REQUIRED_FIELDS: tuple[str, ...] = ("objective", "success_criteria")
MISSION_RECOMMENDED_FIELDS: tuple[str, ...] = ("allowed_actions", "allowed_tools")


def _fact_value(fact: Any) -> Any:
    if isinstance(fact, dict) and set(fact).issuperset({"value"}):
        return deepcopy(fact["value"])
    return deepcopy(fact)


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _profile_default_for_field(
    *, approved_facts: dict[str, Any], provenance: dict[str, Any], field: str
) -> tuple[Any, str | None, dict[str, Any] | None]:
    for category in PROFILE_DEFAULT_FIELD_CATEGORIES.get(field, ()):  # deterministic category precedence
        if category in approved_facts:
            return _fact_value(approved_facts[category]), category, deepcopy(provenance.get(category) or {})
    return None, None, None


def _profile_context(
    *, approved_facts: dict[str, Any], provenance: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    context: dict[str, Any] = {}
    context_provenance: dict[str, Any] = {}
    for category in PROFILE_CONTEXT_CATEGORIES:
        if category not in approved_facts:
            continue
        context[category] = _fact_value(approved_facts[category])
        context_provenance[category] = deepcopy(provenance.get(category) or {})
    return context, context_provenance


def _default_for_field(field: str) -> Any:
    defaults: dict[str, Any] = {
        "constraints": [],
        "context": {},
        "priority": "normal",
        "approval_required": False,
        "approval_expectations": [],
        "budget_limits": None,
        "scope_limits": [],
        "allowed_actions": [],
        "allowed_tools": [],
        "compliance_category": "operational",
        "jurisdiction": "US-ALL",
    }
    return deepcopy(defaults.get(field))


def build_mission_brief_read_model(
    *,
    tenant_id: str,
    approved_facts: dict[str, Any] | None,
    provenance: dict[str, Any] | None,
    current_intent: dict[str, Any],
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic Mission Brief read model without mutation or dispatch authority."""
    profile_facts = deepcopy(approved_facts or {})
    profile_provenance = deepcopy(provenance or {})
    explicit_intent = deepcopy(current_intent)
    explicit_request_context = deepcopy(request_context or {})

    suggested_mission_create: dict[str, Any] = {}
    field_provenance: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    profile_facts_used: set[str] = set()

    for field in MISSION_CREATE_FIELDS:
        if field in explicit_intent and _is_present(explicit_intent[field]):
            value = deepcopy(explicit_intent[field])
            suggested_mission_create[field] = value
            field_provenance[field] = {"source": "mission_input", "authority": "current_mission_intent"}
            profile_value, profile_category, profile_source = _profile_default_for_field(
                approved_facts=profile_facts, provenance=profile_provenance, field=field
            )
            if profile_category is not None and _is_present(profile_value) and profile_value != value:
                profile_facts_used.add(profile_category)
                conflicts.append(
                    {
                        "field": field,
                        "mission_input": value,
                        "business_profile_value": profile_value,
                        "business_profile_category": profile_category,
                        "resolution": "mission_input_wins",
                    }
                )
                field_provenance[field]["conflict"] = {
                    "business_profile_category": profile_category,
                    "business_profile_provenance": profile_source,
                    "resolution": "mission_input_wins",
                }
            continue

        profile_value, profile_category, profile_source = _profile_default_for_field(
            approved_facts=profile_facts, provenance=profile_provenance, field=field
        )
        if profile_category is not None and _is_present(profile_value):
            profile_facts_used.add(profile_category)
            suggested_mission_create[field] = profile_value
            field_provenance[field] = {
                "source": "business_profile",
                "authority": "tenant_approved_profile_fact",
                "profile_category": profile_category,
                "profile_provenance": profile_source,
            }
            continue

        default = _default_for_field(field)
        if default is not None or field in {
            "constraints",
            "context",
            "approval_expectations",
            "scope_limits",
            "allowed_actions",
            "allowed_tools",
        }:
            suggested_mission_create[field] = default
            field_provenance[field] = {"source": "system_default", "authority": "mission_intake_default"}
        else:
            field_provenance[field] = {"source": "missing", "authority": "requires_current_mission_intent"}

    profile_context, profile_context_provenance = _profile_context(
        approved_facts=profile_facts, provenance=profile_provenance
    )
    merged_context = deepcopy(suggested_mission_create.get("context") or {})
    if profile_context:
        existing_profile_context = merged_context.get("business_profile_context")
        if existing_profile_context is not None and existing_profile_context != profile_context:
            conflicts.append(
                {
                    "field": "context.business_profile_context",
                    "mission_input": existing_profile_context,
                    "business_profile_value": profile_context,
                    "resolution": "mission_input_wins",
                }
            )
        else:
            merged_context["business_profile_context"] = profile_context
    if explicit_request_context:
        existing_request_context = merged_context.get("request_context")
        if existing_request_context is not None and existing_request_context != explicit_request_context:
            conflicts.append(
                {
                    "field": "context.request_context",
                    "mission_input": existing_request_context,
                    "request_context": explicit_request_context,
                    "resolution": "mission_input_wins",
                }
            )
        else:
            merged_context["request_context"] = explicit_request_context
    suggested_mission_create["context"] = merged_context
    field_provenance["context"] = {
        **field_provenance.get("context", {"source": "system_default"}),
        "profile_context_categories": sorted(profile_context),
        "profile_context_provenance": profile_context_provenance,
        "request_context_used": bool(explicit_request_context),
    }

    missing_information: list[dict[str, Any]] = []
    for field in MISSION_REQUIRED_FIELDS:
        if not _is_present(suggested_mission_create.get(field)):
            missing_information.append(
                {
                    "field": field,
                    "severity": "blocker",
                    "reason": f"{field} must come from current mission intent before MissionCreate.",
                    "source_required": "mission_input",
                }
            )
    for field in MISSION_RECOMMENDED_FIELDS:
        if not _is_present(suggested_mission_create.get(field)):
            missing_information.append(
                {
                    "field": field,
                    "severity": "warning",
                    "reason": f"{field} is not required by MissionCreate but should be clarified before planning.",
                    "source_required": "mission_input_or_business_profile",
                }
            )

    readiness = {
        "ready_for_mission_create": not any(item["severity"] == "blocker" for item in missing_information),
        "blocker_count": sum(1 for item in missing_information if item["severity"] == "blocker"),
        "warning_count": sum(1 for item in missing_information if item["severity"] == "warning"),
    }

    return {
        "schema_version": MISSION_BRIEF_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "brief": {
            "objective": suggested_mission_create.get("objective"),
            "success_criteria": suggested_mission_create.get("success_criteria") or [],
            "constraints": suggested_mission_create.get("constraints") or [],
            "assumptions": {
                "priority": suggested_mission_create.get("priority"),
                "approval_required": suggested_mission_create.get("approval_required"),
                "budget_limits": suggested_mission_create.get("budget_limits"),
                "scope_limits": suggested_mission_create.get("scope_limits") or [],
                "allowed_actions": suggested_mission_create.get("allowed_actions") or [],
                "allowed_tools": suggested_mission_create.get("allowed_tools") or [],
                "compliance_category": suggested_mission_create.get("compliance_category"),
                "jurisdiction": suggested_mission_create.get("jurisdiction"),
            },
            "business_profile_context": profile_context,
            "request_context": explicit_request_context,
        },
        "missing_information": missing_information,
        "suggested_mission_create": suggested_mission_create,
        "provenance": {
            "fields": field_provenance,
            "profile_facts_used": sorted(profile_facts_used | set(profile_context)),
            "conflicts": conflicts,
        },
        "readiness": readiness,
        "authority_flags": {
            "authority_class": "read_model",
            "mutation_allowed": False,
            "creates_mission": False,
            "creates_mission_plan": False,
            "creates_task_graph": False,
            "creates_execution_tasks": False,
            "queues_work": False,
            "creates_worker_leases": False,
            "creates_evidence_or_outcomes": False,
            "creates_retrieval_or_memory_records": False,
            "runtime_authority": False,
            "requires_explicit_mission_create": True,
            "business_profile_is_runtime_authority": False,
        },
    }
