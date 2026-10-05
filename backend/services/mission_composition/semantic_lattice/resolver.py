"""Deterministic semantic-lattice resolution for the existing vocabulary.

This module owns selection and inheritance traversal. Definitions and their
versioned provenance remain in ``semantic_vocabulary`` during the compatibility
migration; no resolver result can select abilities or grant runtime authority.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from backend.services.mission_composition.semantic_lattice.definitions import (
    _COMPONENT_DOMAIN_ALIASES,
    _COMPONENT_JOB_HINTS,
    _COMPONENT_ORDER,
    _INDUSTRY_COMPONENT_TERMS,
    _LATTICE_COMPONENTS_BY_ID,
    _OUTCOME_CONCEPTS,
    ALL_SEMANTIC_CONCEPTS,
    SHARED_BUSINESS_CONCEPTS_BY_ID,
    SemanticComponentJobGuidance,
    SemanticJobBinding,
    SemanticSelection,
    TenantSemanticOverride,
    normalize_concept_text,
)
from backend.services.mission_composition.semantic_lattice.tenant_overlays import resolve_tenant_aliases


def compose_components(requested: set[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Expand requested components through explicit multi-parent inheritance."""

    expanded: set[str] = set()
    conflicts: list[str] = []

    def visit(component_id: str, trail: tuple[str, ...] = ()) -> None:
        if component_id in expanded:
            return
        component = _LATTICE_COMPONENTS_BY_ID.get(component_id)
        if component is None:
            conflicts.append(f"unknown semantic lattice component: {component_id}")
            return
        if component_id in trail:
            conflicts.append(f"semantic lattice parent cycle: {' -> '.join((*trail, component_id))}")
            return
        for parent in component.parents:
            visit(parent, (*trail, component_id))
        expanded.add(component_id)

    for component_id in requested:
        visit(component_id)
    ordered = tuple(component_id for component_id in _COMPONENT_ORDER if component_id in expanded)
    return ordered, tuple(dict.fromkeys(conflicts))


def build_semantic_selection(
    *,
    instruction: str,
    requested_outcomes: Iterable[str],
    selected_job_keys: Iterable[str],
    tenant_overrides: Iterable[TenantSemanticOverride] = (),
    tenant_override_conflicts: Iterable[str] = (),
) -> SemanticSelection:
    """Resolve concepts, overlays, and advisory job bindings deterministically."""

    selected = tuple(dict.fromkeys(str(item) for item in selected_job_keys if str(item).strip()))
    selected_set = set(selected)
    concepts: list[str] = []
    terms: list[str] = []
    bindings: list[SemanticJobBinding] = []
    tenant_override_items, tenant_aliases, tenant_conflicts = resolve_tenant_aliases(
        tenant_overrides,
        tenant_override_conflicts,
    )
    conflicts = list(tenant_conflicts)

    component_candidates: set[str] = {"shared_business"}
    if requested_outcomes or selected:
        component_candidates.add("gtm.core")
    for raw_outcome in requested_outcomes:
        outcome = normalize_concept_text(str(raw_outcome))
        mapping = _OUTCOME_CONCEPTS.get(outcome)
        if mapping is None:
            continue
        concept_id, expected = mapping
        concept = SHARED_BUSINESS_CONCEPTS_BY_ID[concept_id]
        component_candidates.update(concept.applicable_domains)
        if concept_id not in concepts:
            concepts.append(concept_id)
        binding_status: Literal["satisfied", "conflict"] = (
            "satisfied" if set(expected).issubset(selected_set) else "conflict"
        )
        if binding_status == "conflict":
            conflicts.append(
                f"semantic concept {concept_id} expected jobs {','.join(expected)}; "
                f"selected {','.join(selected) or 'none'}"
            )
        bindings.append(
            SemanticJobBinding(
                concept_id=concept_id,
                concept_version=concept.version,
                source="requested_outcome",
                expected_job_keys=expected,
                selected_job_keys=selected,
                status=binding_status,
            )
        )

    normalized_instruction = normalize_concept_text(instruction)
    for term, component in _INDUSTRY_COMPONENT_TERMS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized_instruction):
            component_candidates.add(component)
    for concept in ALL_SEMANTIC_CONCEPTS:
        matched = next(
            (
                term
                for term in (concept.concept_id, concept.display_name, *concept.aliases)
                if re.search(
                    rf"(?<![a-z0-9]){re.escape(normalize_concept_text(term))}(?![a-z0-9])", normalized_instruction
                )
            ),
            None,
        )
        if matched is None:
            continue
        if concept.concept_id not in concepts:
            concepts.append(concept.concept_id)
        normalized_match = normalize_concept_text(matched)
        if normalized_match not in terms:
            terms.append(normalized_match)
    for alias, concept_id in tenant_aliases.items():
        if not re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_instruction):
            continue
        if concept_id not in concepts:
            concepts.append(concept_id)
        if alias not in terms:
            terms.append(alias)
        component_candidates.update(SHARED_BUSINESS_CONCEPTS_BY_ID[concept_id].applicable_domains)

    normalized_components = {_COMPONENT_DOMAIN_ALIASES.get(component, component) for component in component_candidates}
    active_components, component_conflicts = compose_components(normalized_components)
    conflicts.extend(component_conflicts)
    concept_provenance = tuple(SHARED_BUSINESS_CONCEPTS_BY_ID[concept_id] for concept_id in concepts)
    component_job_guidance = tuple(
        SemanticComponentJobGuidance(
            component_id=component,
            candidate_job_keys=_COMPONENT_JOB_HINTS[component],
            selected_job_keys=selected,
            status=("satisfied" if set(selected).intersection(_COMPONENT_JOB_HINTS[component]) else "informational"),
        )
        for component in active_components
        if component in _COMPONENT_JOB_HINTS
    )
    return SemanticSelection(
        active_components=active_components,
        active_component_provenance=tuple(_LATTICE_COMPONENTS_BY_ID[component] for component in active_components),
        component_conflicts=component_conflicts,
        component_job_guidance=component_job_guidance,
        concepts=tuple(concepts),
        concept_provenance=concept_provenance,
        tenant_overrides=tenant_override_items,
        matched_terms=tuple(terms),
        bindings=tuple(bindings),
        conflicts=tuple(dict.fromkeys(conflicts)),
    )
