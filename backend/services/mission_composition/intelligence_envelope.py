"""Build the additive intelligence handoff envelope."""

from __future__ import annotations

import hashlib

from backend.services.mission_composition.contracts import (
    BusinessJob,
    IntelligenceEnvelope,
    MissionIntent,
    PlannedStepPreview,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_intelligence_envelope(
    *,
    tenant_id: str,
    instruction: str,
    intent: MissionIntent,
    jobs: list[BusinessJob],
    planned_steps: list[PlannedStepPreview],
) -> IntelligenceEnvelope:
    """Project one composition into a replayable, non-authoritative handoff."""

    material_clause_ids = tuple(clause.clause_id for clause in intent.interpreted_clauses if clause.material)
    expected_outputs = tuple(output for job in jobs for output in job.produced_outputs if output)
    input_bindings = tuple(binding for step in planned_steps for binding in step.input_bindings)
    return IntelligenceEnvelope(
        tenant_id=tenant_id,
        instruction_sha256=_sha256(instruction),
        normalized_instruction_sha256=_sha256(intent.normalized_instruction),
        objective=intent.objective,
        requested_outcomes=tuple(intent.requested_outcomes),
        material_clause_ids=material_clause_ids,
        context_requirements=tuple(intent.context_requirements),
        forbidden_actions=tuple(intent.effective_forbidden_actions()),
        expected_outputs=expected_outputs,
        planned_step_keys=tuple(step.step_key for step in planned_steps),
        input_bindings=input_bindings,
        interpretation_evidence=tuple(item.model_dump(mode="json") for item in intent.interpretation_evidence),
    )
