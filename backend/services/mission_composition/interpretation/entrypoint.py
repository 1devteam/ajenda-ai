"""Tenant-aware, non-authoritative canonical mission objective interpretation.

The structured routes keep their original typed action, approval and runtime
authority. This module depends only on semantic interpretation and profile
normalization, not mission composition, persistence or execution.
"""

from __future__ import annotations

from typing import Any, Literal

from backend.services.business_profile.record_sync import build_profile_brief
from backend.services.mission_composition.contracts import MissionIntent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.semantic_lattice.resolver import build_semantic_selection
from backend.services.mission_composition.semantic_vocabulary import TenantSemanticOverride


def _profile_context(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {}
    facts = getattr(profile, "approved_facts", None) or {}
    if not isinstance(facts, dict):
        return {}
    context: dict[str, Any] = {}
    for key in (
        "business_name",
        "company",
        "industry",
        "products_services",
        "target_customers",
        "differentiators",
        "description",
        "service_area",
        "operator_notes",
    ):
        value = facts.get(key)
        if isinstance(value, (str, list, tuple)) and value:
            context[key] = value.strip() if isinstance(value, str) else list(value)
        elif isinstance(value, dict) and value:
            context[key] = value
    # Feed the interpreter the same canonical vocabulary that runtime retrieval
    # emits; this prevents planner context from losing profile fields.
    normalized = build_profile_brief(
        approved_facts=facts,
        provenance=getattr(profile, "provenance", None),
    )["facts"]
    context.update(normalized)
    context["profile_id"] = str(getattr(profile, "id", ""))
    return context


def _tenant_semantic_overrides(profile: Any) -> tuple[tuple[TenantSemanticOverride, ...], tuple[str, ...]]:
    """Read approved tenant aliases without changing the shared vocabulary."""

    if profile is None:
        return (), ()
    facts = getattr(profile, "approved_facts", None) or {}
    if not isinstance(facts, dict) or "semantic_terminology_overrides" not in facts:
        return (), ()
    raw = facts.get("semantic_terminology_overrides")
    if not isinstance(raw, list):
        return (), ("tenant semantic terminology overrides must be a list",)

    profile_id = str(getattr(profile, "id", "unknown"))
    overrides: list[TenantSemanticOverride] = []
    conflicts: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            conflicts.append(f"tenant semantic override {index} must be an object")
            continue
        payload = dict(item)
        payload.setdefault("source_reference", f"business_profile:{profile_id}")
        payload.setdefault("version", "1.0.0")
        try:
            overrides.append(TenantSemanticOverride.model_validate(payload))
        except ValueError as exc:
            conflicts.append(f"tenant semantic override {index} is invalid: {str(exc)[:240]}")
    return tuple(overrides), tuple(conflicts)


def interpret_instruction_with_profile(
    instruction: str,
    *,
    profile: Any,
) -> tuple[MissionIntent, tuple[TenantSemanticOverride, ...], tuple[str, ...]]:
    """Share the canonical interpreter input contract across mission entry points.

    Approved business terminology may inform meaning, but never grants an
    action or replaces the structured intake's explicit policies and limits.
    """
    overrides, override_conflicts = _tenant_semantic_overrides(profile)
    concept_selection = build_semantic_selection(
        instruction=instruction,
        requested_outcomes=(),
        selected_job_keys=(),
        tenant_overrides=overrides,
        tenant_override_conflicts=override_conflicts,
        validate_job_bindings=False,
    )
    intent = interpret_instruction(
        instruction,
        profile_context=_profile_context(profile),
        semantic_selection=concept_selection,
    )
    return intent, overrides, override_conflicts


def build_objective_interpretation_snapshot(
    instruction: str,
    *,
    profile: Any,
    source_kind: Literal["direct_intake", "vertical_template", "ability_action"],
    input_origin: Literal["user", "template", "generated_action"] = "user",
) -> dict[str, Any]:
    """Produce a typed, non-authoritative interpretation for a mission entry.

    This interprets the objective only. Structured action IDs, field values,
    approvals and explicit policy contracts stay owned by their source route.
    """
    intent, _, _ = interpret_instruction_with_profile(instruction, profile=profile)
    return {
        "schema_version": 1,
        "source_kind": source_kind,
        "input_origin": input_origin,
        "input_scope": "objective_only",
        "interpretation_usage": "diagnostic_only",
        "authority_class": "read_model",
        "grants_execution_authority": False,
        "intent": intent.model_dump(mode="json"),
    }


