"""Canonical user-review projection for a model-produced mission intent."""

from __future__ import annotations

from typing import Any

from backend.services.mission_composition.contracts import MissionIntent


def reviewed_interpretation_payload(intent: MissionIntent) -> dict[str, Any]:
    """Return every model-derived field that can affect mission composition.

    Raw user wording, interpreter evidence, and backend readiness bookkeeping
    are intentionally excluded. The returned projection is both displayed to
    the user and fingerprinted, preventing hidden execution-relevant meaning.
    """

    return {
        "interpreted_instruction": intent.normalized_instruction,
        "requested_outcomes": list(intent.requested_outcomes),
        "unsupported_outcomes": list(intent.unsupported_outcomes),
        "requested_quantity": intent.requested_quantity,
        "send_policy": intent.send_policy.model_dump(mode="json"),
        "contact_policy": intent.contact_policy.model_dump(mode="json"),
        "publish_policy": intent.publish_policy.model_dump(mode="json"),
        "write_policy": intent.write_policy.model_dump(mode="json"),
        "target_entities": [item.model_dump(mode="json") for item in intent.target_entities],
        "timing_constraints": [item.model_dump(mode="json") for item in intent.timing_constraints],
        "constraints": list(intent.constraints),
        "forbidden_outcomes": list(intent.forbidden_canonical_outcomes),
        "success_criteria": [item.model_dump(mode="json") for item in intent.success_criteria],
        "approval_preference": intent.approval_preference,
        "context_requirements": list(intent.context_requirements),
        "clarifications": [item.model_dump(mode="json") for item in intent.ambiguity],
        "contradictions": [item.model_dump(mode="json") for item in intent.contradictions],
    }


def confirmed_intent_payload(intent: MissionIntent) -> dict[str, Any]:
    """Return the confirmed intent without original-language audit spans.

    The durable proposal owns raw/source evidence for backend audit. Mission
    lifecycle reads are browser-visible, so their stored intent contains only
    the reviewed interpretation and semantic fields required for deterministic
    recompilation.
    """

    sanitized = intent.model_copy(
        update={
            "raw_instruction": "",
            "ambiguity": [],
            "interpreted_clauses": [],
            "unmatched_material_clauses": [],
            "semantic_units": [],
            "unmatched_material_units": [],
            "contradictions": [],
            "interpretation_evidence": [],
        }
    )
    return sanitized.model_dump(mode="json")


__all__ = ["confirmed_intent_payload", "reviewed_interpretation_payload"]
