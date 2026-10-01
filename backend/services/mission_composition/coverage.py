"""Deterministic mission applicability and source-capacity assessment.

This module is composition metadata only. It does not select handlers,
resolve credentials, create tasks, access providers, or grant runtime
authority. It makes known source-capacity limits visible before queue
admission.
"""

from __future__ import annotations

import re

from backend.services.ajenda_demo_fixtures import supplemental_demo_records
from backend.services.mission_composition.contracts import (
    CoverageAssessment,
    CoverageMode,
    CoverageStatus,
    MissionIntent,
)

COVERAGE_SCHEMA_VERSION = 1


def _source_mode(intent: MissionIntent) -> CoverageMode:
    text = intent.raw_instruction.casefold()
    if re.search(r"\blocal\s+(?:test\s+)?fixtures?\b|\bfixture\s+data\s+only\b", text):
        return "local_fixture"
    if "internal_crm_source" in intent.context_requirements or re.search(
        r"\b(?:ajenda(?:['\u2019]s)?\s+internal\s+crm|internal\s+(?:ajenda\s+)?crm)\b", text
    ):
        return "internal_crm"
    if intent.target_entities or intent.requested_outcomes:
        return "public_or_provider"
    return "unknown"


def _scope(intent: MissionIntent) -> tuple[str | None, str | None, str | None]:
    for entity in intent.target_entities:
        if entity.industry and entity.location:
            industry = " ".join(entity.industry.casefold().split())
            location = " ".join(entity.location.casefold().split())
            return industry, location, f"{industry}:{location}"
    return None, None, None


def _fixture_capacity(industry: str, location: str) -> int:
    accounts = supplemental_demo_records().get("account", {})
    return sum(
        1
        for record in accounts.values()
        if str(record.get("industry", "")).casefold() == industry
        and str(record.get("location", "")).casefold() == location
    )


def assess_coverage(intent: MissionIntent) -> CoverageAssessment:
    """Assess known applicability/capacity without touching runtime state."""

    mode = _source_mode(intent)
    requested = intent.requested_quantity or intent.qualification_quantity or 3
    if mode in {"internal_crm", "public_or_provider", "unknown"}:
        return CoverageAssessment(
            mode=mode,
            status="unknown",
            requested_quantity=requested,
            reasons=("source_capacity_requires_runtime_or_provider_observation",),
            source_reference="mission_intent_and_runtime_source_contracts",
        )

    industry, location, scope_key = _scope(intent)
    if not industry or not location:
        return CoverageAssessment(
            mode="local_fixture",
            status="unsupported_scope",
            requested_quantity=requested,
            reasons=("local_fixture_requires_explicit_industry_and_location",),
            source_reference="ajenda_demo_fixtures.supplemental_demo_records",
        )

    capacity = _fixture_capacity(industry, location)
    if capacity == 0:
        return CoverageAssessment(
            mode="local_fixture",
            status="unsupported_scope",
            scope_key=scope_key,
            requested_quantity=requested,
            available_quantity=0,
            reasons=("no_local_fixture_scope_for_industry_location",),
            source_reference="ajenda_demo_fixtures.supplemental_demo_records",
        )
    if capacity < requested:
        return CoverageAssessment(
            mode="local_fixture",
            status="insufficient_capacity",
            scope_key=scope_key,
            requested_quantity=requested,
            available_quantity=capacity,
            reasons=("requested_quantity_exceeds_local_fixture_capacity",),
            source_reference="ajenda_demo_fixtures.supplemental_demo_records",
        )
    status: CoverageStatus = "supported_with_limits" if capacity == requested else "supported"
    return CoverageAssessment(
        mode="local_fixture",
        status=status,
        scope_key=scope_key,
        requested_quantity=requested,
        available_quantity=capacity,
        reasons=("local_fixture_scope_and_capacity_known",),
        source_reference="ajenda_demo_fixtures.supplemental_demo_records",
    )
