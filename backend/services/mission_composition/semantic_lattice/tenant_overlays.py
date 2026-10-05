"""Tenant-private semantic overlays for the modular semantic lattice.

Tenant terminology is an interpretation aid only.  This module deliberately
does not mutate shared definitions or select executable jobs.
"""

from __future__ import annotations

from collections.abc import Iterable

from backend.services.mission_composition.semantic_lattice.definitions import (
    ALL_SEMANTIC_CONCEPTS,
    SHARED_BUSINESS_CONCEPTS_BY_ID,
    TenantSemanticOverride,
    normalize_concept_text,
)


def resolve_tenant_aliases(
    overrides: Iterable[TenantSemanticOverride],
    initial_conflicts: Iterable[str] = (),
) -> tuple[tuple[TenantSemanticOverride, ...], dict[str, str], tuple[str, ...]]:
    """Validate tenant aliases without changing shared vocabulary.

    Returns the immutable override tuple, normalized alias map, and
    deterministic conflict list.  Unknown concepts and collisions fail closed
    as semantic conflicts; they never become runtime authority.
    """

    items = tuple(overrides)
    aliases: dict[str, str] = {}
    conflicts = [str(item) for item in initial_conflicts]
    shared_aliases = {
        normalize_concept_text(value): concept.concept_id
        for concept in ALL_SEMANTIC_CONCEPTS
        for value in (concept.concept_id, concept.display_name, *concept.aliases)
    }
    for override in items:
        if override.concept_id not in SHARED_BUSINESS_CONCEPTS_BY_ID:
            conflicts.append(f"tenant semantic override references unknown concept: {override.concept_id}")
            continue
        for alias in override.aliases:
            normalized = normalize_concept_text(alias)
            shared_concept_id = shared_aliases.get(normalized)
            if shared_concept_id is not None and shared_concept_id != override.concept_id:
                conflicts.append(
                    f"tenant semantic alias conflict: {normalized!r} maps to shared concept "
                    f"{shared_concept_id} and tenant concept {override.concept_id}"
                )
                continue
            prior = aliases.get(normalized)
            if prior is not None and prior != override.concept_id:
                conflicts.append(
                    f"tenant semantic alias conflict: {normalized!r} maps to {prior} and {override.concept_id}"
                )
                continue
            aliases[normalized] = override.concept_id
    return items, aliases, tuple(dict.fromkeys(conflicts))
