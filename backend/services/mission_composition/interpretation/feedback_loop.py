"""Bounded feedback for the existing mission interpreter.

No job selection, execution authority, persistence, or failure evaluation lives here.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.contracts import MissionIntent
from backend.services.mission_composition.semantic_lattice.definitions import SemanticSelection, normalize_concept_text
from backend.services.mission_composition.semantic_lattice.resolver import build_semantic_selection


_SEMANTIC_QUALIFICATION_REQUEST = re.compile(
    r"\b(?:assess|evaluate|analy[sz]e|measure)\b[^.!?]{0,80}\b(?:lead quality|qualification)\b",
    re.IGNORECASE,
)
_SEMANTIC_QUALIFICATION_NEGATION = re.compile(
    r"\b(?:do not|don't|dont|never|without)\b[^.!?]{0,80}"
    r"\b(?:assess|evaluate|analy[sz]e|measure)\b",
    re.IGNORECASE,
)
_MAX_INTERPRETATION_PASSES = 3


def _semantic_outcome_feedback(
    instruction: str,
    selection: SemanticSelection,
    intent: MissionIntent,
) -> frozenset[str]:
    """Return explicitly grounded, previously unresolved canonical meanings.

    A concept or noun alone never requests a job. The user must supply an
    affirmative qualifying verb and an exact lattice-recognized concept.
    """
    normalized = normalize_concept_text(instruction)
    if (
        "qualify_prospects" not in intent.requested_outcomes
        and "qualification" in selection.concepts
        and {"lead quality", "qualification"}.intersection(selection.matched_terms)
        and _SEMANTIC_QUALIFICATION_REQUEST.search(normalized)
        and not _SEMANTIC_QUALIFICATION_NEGATION.search(normalized)
    ):
        return frozenset({"qualify_prospects"})
    return frozenset()


def interpret_with_semantic_feedback(
    instruction: str,
    *,
    profile_context: dict[str, Any] | None = None,
    spelling_enabled: bool | None = None,
    fuzzy_enabled: bool | None = None,
    semantic_selection: SemanticSelection | None = None,
) -> MissionIntent:
    """Interpret, revisit grounded unresolved meaning, and stop at convergence.

    Each re-entry reruns the original interpreter from the raw instruction.
    Only exact semantic evidence with an explicit user action may influence an
    unresolved outcome. Existing policy, entity and quantity contracts cannot
    be overwritten by a later pass.
    """
    from backend.services.mission_composition import intent_interpreter as interpreter_module

    selection = semantic_selection
    if selection is None:
        selection = build_semantic_selection(
            instruction=instruction,
            requested_outcomes=(),
            selected_job_keys=(),
        )
    current = interpreter_module._interpret_instruction_pass(
        instruction,
        profile_context=profile_context,
        spelling_enabled=spelling_enabled,
        fuzzy_enabled=fuzzy_enabled,
        semantic_selection=selection,
    )
    seen = {(tuple(current.requested_outcomes), tuple(selection.concepts))}
    for _ in range(1, _MAX_INTERPRETATION_PASSES):
        # Let candidate meaning inform the *same* lattice before revisiting
        # interpretation. No jobs have been selected yet, so job checks are
        # informational only and cannot produce premature job conflicts.
        next_selection = build_semantic_selection(
            instruction=instruction,
            requested_outcomes=current.requested_outcomes,
            selected_job_keys=(),
            tenant_overrides=selection.tenant_overrides,
            tenant_override_conflicts=selection.conflicts,
            validate_job_bindings=False,
        )
        hints = _semantic_outcome_feedback(instruction, next_selection, current)
        concepts_changed = set(next_selection.concepts) != set(selection.concepts)
        if not hints and not concepts_changed:
            break
        candidate = interpreter_module._interpret_instruction_pass(
            instruction,
            profile_context=profile_context,
            spelling_enabled=spelling_enabled,
            fuzzy_enabled=fuzzy_enabled,
            semantic_selection=next_selection,
            semantic_outcome_hints=hints,
        )
        signature = (tuple(candidate.requested_outcomes), tuple(next_selection.concepts))
        if signature in seen:
            break
        seen.add(signature)
        if not hints.issubset(set(candidate.requested_outcomes)):
            break
        # Re-entry may enrich meaning, but cannot remove user intent, downgrade
        # interpretation readiness or rewrite source/authority contracts.
        if not set(current.requested_outcomes).issubset(candidate.requested_outcomes):
            break
        if current.interpretation_ready and not candidate.interpretation_ready:
            break
        if (
            candidate.target_entities != current.target_entities
            or candidate.requested_quantity != current.requested_quantity
            or candidate.qualification_quantity != current.qualification_quantity
            or candidate.send_policy != current.send_policy
            or candidate.contact_policy != current.contact_policy
            or candidate.publish_policy != current.publish_policy
            or candidate.write_policy != current.write_policy
            or candidate.timing_constraints != current.timing_constraints
            or candidate.forbidden_actions != current.forbidden_actions
            or candidate.forbidden_canonical_outcomes != current.forbidden_canonical_outcomes
            or candidate.constraints != current.constraints
            or candidate.contradictions != current.contradictions
        ):
            break
        current = candidate
        selection = next_selection
    return current
