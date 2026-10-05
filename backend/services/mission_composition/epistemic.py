"""Deterministic epistemic context for mission composition.

The context describes what is known before runtime observation. It does not
retrieve data, evaluate providers, resolve credentials, or grant authority.
"""

from __future__ import annotations

from typing import Literal

from backend.services.mission_composition.contracts import (
    CoverageAssessment,
    EpistemicBudget,
    EpistemicContext,
    EpistemicContradictionStatus,
    EpistemicSourceClass,
    MissionIntent,
)


def build_epistemic_context(
    intent: MissionIntent,
    coverage: CoverageAssessment,
) -> EpistemicContext:
    """Build a bounded pre-runtime knowledge read model from intent evidence."""

    sources: set[EpistemicSourceClass] = set()
    if intent.raw_instruction.strip():
        sources.add("explicit_user")
    if any(item.provenance == "profile_context" for item in intent.target_entities):
        sources.add("tenant_profile")
    if coverage.mode == "local_fixture":
        sources.add("local_fixture")
    elif coverage.mode == "internal_crm":
        sources.add("internal_crm")
    elif coverage.mode == "public_or_provider":
        sources.add("public_observation")
    if intent.interpretation_evidence:
        sources.add("derived")
    if not sources:
        sources.add("unknown")

    unresolved = sum(1 for contradiction in intent.contradictions if contradiction.resolution_status == "unresolved")
    contradiction_status: EpistemicContradictionStatus
    if unresolved:
        contradiction_status = "unresolved"
    elif intent.contradictions:
        contradiction_status = "resolved"
    else:
        contradiction_status = "none"

    required: list[str] = []
    missing: list[str] = []
    if coverage.mode in {"public_or_provider", "internal_crm"}:
        required.append("runtime_source_observation")
        missing.append("runtime_source_observation")
    if coverage.mode == "local_fixture" and coverage.status not in {"supported", "supported_with_limits"}:
        required.append("supported_fixture_scope")
        missing.append("supported_fixture_scope")
    if intent.contradictions:
        required.append("contradiction_resolution")
        if unresolved:
            missing.append("contradiction_resolution")

    # This is an interpretation-policy estimate until runtime calibration
    # exists; it is not a measured probability.
    confidence = intent.minimum_field_confidence
    if confidence is None:
        confidence = min((item.confidence for item in intent.interpretation_evidence), default=0.0)
    confidence_basis = ["mission_intent"]
    if intent.interpretation_evidence:
        confidence_basis.append("deterministic_interpretation_evidence")
    if coverage.mode == "local_fixture":
        confidence_basis.append("fixture_catalog_scope")

    if coverage.mode == "local_fixture":
        tolerance: Literal["strict", "standard", "exploratory"] = "strict"
        max_missing_evidence = 0
    elif coverage.mode in {"public_or_provider", "internal_crm"}:
        tolerance = "standard"
        max_missing_evidence = 1
    else:
        tolerance = "exploratory"
        max_missing_evidence = 2
    budget = EpistemicBudget(
        tolerance=tolerance,
        max_missing_evidence=max_missing_evidence,
        minimum_confidence=0.7 if intent.interpretation_ready else 0.0,
    )
    budget_excesses: list[str] = []
    if len(missing) > budget.max_missing_evidence:
        budget_excesses.append(f"missing_evidence:{len(missing)}>{budget.max_missing_evidence}")
    if unresolved > budget.max_unresolved_contradictions:
        budget_excesses.append(f"unresolved_contradictions:{unresolved}>{budget.max_unresolved_contradictions}")
    if confidence < budget.minimum_confidence:
        budget_excesses.append(f"confidence:{confidence:.2f}<{budget.minimum_confidence:.2f}")
    if "unknown" in sources and not budget.allow_unknown_sources:
        budget_excesses.append("unknown_sources")

    return EpistemicContext(
        source_classes=tuple(sorted(sources)),
        confidence=confidence,
        confidence_semantics="policy_estimate",
        confidence_basis=tuple(confidence_basis),
        freshness="not_observed",
        contradiction_status=contradiction_status,
        unresolved_contradiction_count=unresolved,
        required_evidence=tuple(dict.fromkeys(required)),
        missing_evidence=tuple(dict.fromkeys(missing)),
        budget=budget,
        budget_status="exceeded" if budget_excesses else "within_budget",
        budget_excesses=tuple(budget_excesses),
    )
