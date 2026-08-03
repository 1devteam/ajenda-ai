"""Focused fixtures for the untrusted mission-interpreter boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.services.mission_composition.contracts import (
    InterpretationEvidence,
    InterpretedClause,
    MissionIntent,
    SemanticUnit,
    SendPolicy,
    StructuredPolicy,
    SuccessCriterion,
    TargetEntity,
)
from backend.services.mission_composition.interpretation.llm_client import MissionInterpretationRequest
from backend.services.mission_composition.interpretation.schema import (
    GroundedOutcome,
    GroundedPolicy,
    InterpretationSegment,
    LlmMissionInterpretation,
)


def ready_intent(
    instruction: str,
    *,
    interpreted_instruction: str | None = None,
    outcomes: tuple[str, ...] = ("research_prospects",),
    quantity: int | None = None,
    send_mode: str = "forbid",
    send_condition: str = "none",
    targets: list[TargetEntity] | None = None,
    constraints: list[str] | None = None,
    context_requirements: list[str] | None = None,
) -> MissionIntent:
    """Build an already-validated intent so downstream tests do not parse prose."""

    evidence = [
        InterpretationEvidence(
            field_path=f"requested_outcomes[{index}]",
            source="explicit",
            source_text=instruction,
            normalized_value=outcome,
            confidence=1.0,
            rule_id="test.interpreter",
            components_active=["test_interpreter"],
        )
        for index, outcome in enumerate(outcomes)
    ]
    return MissionIntent(
        raw_instruction=instruction,
        normalized_instruction=interpreted_instruction or instruction,
        objective=interpreted_instruction or instruction,
        requested_outcomes=list(outcomes),
        requested_quantity=quantity,
        quantity_provenance="explicit" if quantity is not None else None,
        send_policy=SendPolicy(
            mode=send_mode,  # type: ignore[arg-type]
            condition=send_condition,  # type: ignore[arg-type]
            source="explicit",
            confidence=1.0,
            rule_id="test.send_policy",
        ),
        contact_policy=StructuredPolicy(),
        publish_policy=StructuredPolicy(),
        write_policy=StructuredPolicy(),
        target_entities=list(targets or []),
        constraints=list(constraints or []),
        success_criteria=[SuccessCriterion(description="Produce the requested governed result")],
        context_requirements=list(context_requirements or []),
        interpreted_clauses=[
            InterpretedClause(
                clause_id="test-clause-1",
                text=instruction,
                status="recognized",
                mapped_outcomes=list(outcomes),
            )
        ],
        semantic_units=[
            SemanticUnit(
                unit_id="test-unit-1",
                kind="action",
                text=instruction,
                accounted=True,
                mapped_outcomes=list(outcomes),
            )
        ],
        interpretation_evidence=evidence,
        coverage_score=1.0,
        minimum_field_confidence=1.0,
        interpretation_ready=True,
        components_available=["test_interpreter"],
        components_executed=["test_interpreter"],
        components_contributing=["test_interpreter"],
        components_active=["test_interpreter"],
    )


@dataclass
class StaticMissionInterpreter:
    intent: MissionIntent
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def interpret(self, instruction: str, *, profile_context: dict[str, Any] | None = None) -> MissionIntent:
        self.calls.append((instruction, dict(profile_context or {})))
        return self.intent.model_copy(
            update={
                "raw_instruction": instruction,
                "normalized_instruction": self.intent.normalized_instruction,
            }
        )


@dataclass
class StaticMissionInterpreterClient:
    interpretation: LlmMissionInterpretation
    model: str = "test-local-model"
    requests: list[MissionInterpretationRequest] = field(default_factory=list)

    def interpret(self, request: MissionInterpretationRequest) -> LlmMissionInterpretation:
        self.requests.append(request)
        return self.interpretation


def llm_interpretation(
    instruction: str,
    *,
    interpreted_instruction: str | None = None,
    outcomes: tuple[str, ...] = ("research_prospects",),
    quantity: int | None = None,
    quantity_source_text: str | None = None,
    send_policy: GroundedPolicy | None = None,
    segments: list[InterpretationSegment] | None = None,
) -> LlmMissionInterpretation:
    return LlmMissionInterpretation(
        interpreted_instruction=interpreted_instruction or instruction,
        requested_outcomes=[
            GroundedOutcome(outcome=outcome, source_text=instruction)  # type: ignore[arg-type]
            for outcome in outcomes
        ],
        requested_quantity=quantity,
        quantity_source_text=quantity_source_text,
        send_policy=send_policy or GroundedPolicy(),
        segments=segments
        or [
            InterpretationSegment(
                source_text=instruction,
                normalized_text=interpreted_instruction or instruction,
                kind="action",
                accounted=True,
                mapped_outcomes=list(outcomes),
            )
        ],
    )
