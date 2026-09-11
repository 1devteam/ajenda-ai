"""Canonical business-first categories for approved profile facts."""

from __future__ import annotations

from typing import Final

BUSINESS_PROFILE_CATEGORY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "company": ("business_name", "industry", "description", "service_area", "operator_notes"),
    "market": ("target_customers", "differentiators"),
    "offer": ("products_services",),
    "governance": ("operating_charter",),
    "growth": ("growth_goals", "acquisition_channels", "outreach_preferences", "content_themes"),
    "customer_insight": ("customer_interviews", "customer_polls", "customer_tests", "validation_criteria"),
    "delivery": ("delivery_process", "service_constraints", "support_model"),
    "metrics": ("success_metrics", "targets", "guardrails"),
}

PROFILE_CATEGORY_BY_FIELD: Final[dict[str, str]] = {
    field: category for category, fields in BUSINESS_PROFILE_CATEGORY_FIELDS.items() for field in fields
}

# Mission Brief and onboarding still carry a bounded set of legacy profile keys.
# Keep those keys readable while assigning them to the same business-first taxonomy.
PROFILE_CATEGORY_BY_FIELD.update(
    {
        "name": "company",
        "success_criteria": "metrics",
        "evidence_expectations": "governance",
        "constraints": "delivery",
        "operating_constraints": "delivery",
        "allowed_actions": "governance",
        "allowed_tools": "governance",
        "scope_limits": "governance",
        "approval_required": "governance",
        "approval_expectations": "governance",
        "budget_limits": "metrics",
        "compliance_category": "governance",
        "jurisdiction": "governance",
    }
)


def profile_category_for_field(field: str) -> str | None:
    """Return the canonical category for a profile field, if one is known."""

    normalized = field.strip()
    direct = PROFILE_CATEGORY_BY_FIELD.get(normalized)
    if direct is not None:
        return direct
    if normalized.startswith("default_"):
        return PROFILE_CATEGORY_BY_FIELD.get(normalized.removeprefix("default_"))
    return normalized if normalized in BUSINESS_PROFILE_CATEGORY_FIELDS else None


def missing_profile_categories(approved_facts: object, required_categories: tuple[str, ...]) -> list[str]:
    """Return required categories with no non-empty approved profile fact."""

    if not isinstance(approved_facts, dict):
        return list(required_categories)
    present: set[str] = set()
    for field, value in approved_facts.items():
        if not isinstance(field, str) or not value:
            continue
        if isinstance(value, dict):
            value = value.get("value") or value.get("default") or value.get("items") or value.get("values")
        if not value:
            continue
        category = profile_category_for_field(field)
        if category is not None:
            present.add(category)
    return [category for category in required_categories if category not in present]
