"""Deterministic epistemic context for mission composition.

The context describes what is known before runtime observation. It does not
retrieve data, evaluate providers, resolve credentials, or grant authority.
"""

from __future__ import annotations

from backend.services.mission_composition.contracts import (
    CoverageAssessment,
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

    confidence = intent.minimum_field_confidence
    if confidence is None:
        confidence = min((item.confidence for item in intent.interpretation_evidence), default=0.0)
    confidence_basis = ["mission_intent"]
    if intent.interpretation_evidence:
        confidence_basis.append("deterministic_interpretation_evidence")
    if coverage.mode == "local_fixture":
        confidence_basis.append("fixture_catalog_scope")

    return EpistemicContext(
        source_classes=tuple(sorted(sources)),
        confidence=confidence,
        confidence_basis=tuple(confidence_basis),
        freshness="not_observed",
        contradiction_status=contradiction_status,
        unresolved_contradiction_count=unresolved,
        required_evidence=tuple(dict.fromkeys(required)),
        missing_evidence=tuple(dict.fromkeys(missing)),
    )
