"""Bounded feedback for the existing mission interpreter.

No job selection, execution authority, persistence, or failure evaluation lives here.
"""

from __future__ import annotations

import re
from typing import Any

from backend.services.mission_composition.contracts import InterpretationPassTrace, MissionIntent
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

    history = [
        InterpretationPassTrace(
            pass_number=1,
            requested_outcomes=tuple(current.requested_outcomes),
            concept_ids=selection.concepts,
            decision="initial",
            reason="initial_interpretation",
        )
    ]
    seen = {(tuple(current.requested_outcomes), tuple(selection.concepts))}
    stop_reason = "converged"
    initial_conflicts = selection.conflicts
    for pass_number in range(2, _MAX_INTERPRETATION_PASSES + 1):
        # The lattice consumes candidate meaning without checking for jobs that
        # cannot exist until the interpreter has finished.
        next_selection = build_semantic_selection(
            instruction=instruction,
            requested_outcomes=current.requested_outcomes,
            selected_job_keys=(),
            tenant_overrides=selection.tenant_overrides,
            tenant_override_conflicts=initial_conflicts,
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
        rejection = ""
        if signature in seen:
            rejection = "repeated_interpretation"
            stop_reason = "cycle"
        elif not hints.issubset(set(candidate.requested_outcomes)):
            rejection = "feedback_not_grounded"
        elif not set(current.requested_outcomes).issubset(candidate.requested_outcomes):
            rejection = "existing_outcome_removed"
        elif current.interpretation_ready and not candidate.interpretation_ready:
            rejection = "readiness_regressed"
        elif (
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
            rejection = "source_or_authority_contract_changed"
        history.append(
            InterpretationPassTrace(
                pass_number=pass_number,
                requested_outcomes=tuple(candidate.requested_outcomes),
                concept_ids=next_selection.concepts,
                feedback_hints=tuple(sorted(hints)),
                decision="rejected" if rejection else "accepted",
                reason=rejection or "new_semantic_information",
            )
        )
        if rejection:
            if stop_reason != "cycle":
                stop_reason = "rejected"
            break
        seen.add(signature)
        current = candidate
        selection = next_selection
    else:
        stop_reason = "pass_limit"
    return current.model_copy(
        update={
            "interpretation_passes": history,
            "interpretation_stop_reason": stop_reason,
        }
    )
