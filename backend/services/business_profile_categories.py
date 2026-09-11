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


def profile_category_for_field(field: str) -> str | None:
    """Return the canonical category for a profile field, if one is known."""

    return PROFILE_CATEGORY_BY_FIELD.get(field.strip())
