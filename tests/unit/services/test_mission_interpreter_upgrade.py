"""Mission-language interpreter boundary and meaning-guard tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.mission_composition.interpretation.interpreter import (
    LlmMissionInterpreter,
    MissionInterpreterOutputError,
)
from backend.services.mission_composition.interpretation.schema import (
    GroundedContextRequirement,
    GroundedPolicy,
    GroundedTarget,
    GroundedUnsupportedOutcome,
    InterpretationClarification,
    InterpretationContradiction,
    InterpretationSegment,
)
from tests.mission_interpreter_fakes import StaticMissionInterpreterClient, llm_interpretation


def test_shorthand_and_misspellings_become_reviewable_intent_without_authority() -> None:
    raw = "fnd 3 roofers in austin n draft intros dont send"
    candidate = llm_interpretation(
        raw,
        interpreted_instruction=(
            "Find 3 roofing companies in Austin and draft introductions. Do not send the introductions."
        ),
        outcomes=("research_prospects", "prepare_outreach"),
        quantity=3,
        quantity_source_text="3",
        send_policy=GroundedPolicy(
            mode="forbid",
            condition="none",
            source_text="dont send",
            confidence=1.0,
        ),
    ).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="market",
                    source_text="roofers in austin",
                    industry="roofing",
                    location="Austin",
                )
            ]
        }
    )
    client = StaticMissionInterpreterClient(candidate)

    intent = LlmMissionInterpreter(client=client).interpret(raw)

    assert intent.raw_instruction == raw
    assert intent.normalized_instruction == candidate.interpreted_instruction
    assert intent.requested_outcomes == ["research_prospects", "prepare_outreach"]
    assert intent.requested_quantity == 3
    assert intent.send_policy.mode == "forbid"
    assert intent.effective_forbidden_actions() == ["gtm.email_send"]
    assert intent.interpretation_ready is True
    assert intent.components_executed == ["local_llm", "json_schema", "meaning_guard"]
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    ("raw", "interpreted", "expected_code"),
    [
        (
            "Draft an introduction email.",
            "Draft an introduction email to ceo@example.com.",
            "INTERPRETER_INVENTED_RECIPIENT",
        ),
        (
            "Find roofing companies in Austin.",
            "Find 10 roofing companies in Austin.",
            "INTERPRETER_INVENTED_QUANTITY",
        ),
        (
            "Review the company website.",
            "Review https://example.com.",
            "INTERPRETER_INVENTED_URL",
        ),
    ],
)
def test_protected_facts_cannot_be_invented(raw: str, interpreted: str, expected_code: str) -> None:
    candidate = llm_interpretation(raw, interpreted_instruction=interpreted)
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == expected_code


@pytest.mark.parametrize(
    ("raw", "interpreted", "targets", "expected_code"),
    [
        (
            "Draft an email to ceo@example.com.",
            "Draft an email.",
            [],
            "INTERPRETER_DROPPED_RECIPIENT",
        ),
        (
            "Draft an email to ceo@example.com.",
            "Draft an email to ceo@example.com.",
            [],
            "INTERPRETER_DROPPED_RECIPIENT",
        ),
        (
            "Review https://example.com/pricing.",
            "Review the pricing page.",
            [],
            "INTERPRETER_DROPPED_URL",
        ),
        (
            "Review https://example.com/pricing.",
            "Review https://example.com/pricing.",
            [],
            "INTERPRETER_DROPPED_URL",
        ),
    ],
)
def test_supplied_recipients_and_urls_must_survive_echo_and_schema(
    raw: str,
    interpreted: str,
    targets: list[GroundedTarget],
    expected_code: str,
) -> None:
    candidate = llm_interpretation(raw, interpreted_instruction=interpreted).model_copy(
        update={"target_entities": targets}
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == expected_code


@pytest.mark.parametrize(
    "interpreted",
    [
        "Find roofing companies in Austin.",
        "Find 3 roofing companies in Austin.",
    ],
)
def test_supplied_number_must_survive_echo_and_structured_details(interpreted: str) -> None:
    raw = "Find 3 roofers in Austin."
    candidate = llm_interpretation(raw, interpreted_instruction=interpreted)
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_DROPPED_QUANTITY"


def test_supplied_protected_facts_can_survive_echo_and_corresponding_schema() -> None:
    raw = "Review https://example.com/pricing and draft 3 emails to ceo@example.com."
    candidate = llm_interpretation(
        raw,
        quantity=3,
        quantity_source_text="3",
    ).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="company",
                    source_text="https://example.com/pricing",
                    url="https://example.com/pricing",
                ),
                GroundedTarget(
                    type="recipient",
                    source_text="ceo@example.com",
                    email="ceo@example.com",
                ),
            ]
        }
    )

    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)

    assert intent.requested_quantity == 3
    assert {item.url for item in intent.target_entities if item.url} == {"https://example.com/pricing"}
    assert {item.email for item in intent.target_entities if item.email} == {"ceo@example.com"}


def test_structured_quantity_must_match_its_grounded_source_span() -> None:
    raw = "Find three roofing companies in Austin."
    candidate = llm_interpretation(
        raw,
        quantity=10,
        quantity_source_text="three",
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_INVENTED_QUANTITY"


def test_ungrounded_structured_field_fails_closed() -> None:
    raw = "Find roofers in Austin."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="market",
                    source_text="roofers in Dallas",
                    industry="roofing",
                    location="Dallas",
                )
            ]
        }
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_UNGROUNDED_OUTPUT"


def test_target_fields_cannot_invent_values_inside_a_real_source_span() -> None:
    raw = "Find roofers in Austin."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="market",
                    source_text="roofers in Austin",
                    name="Pfizer",
                    industry="pharmaceutical",
                    location="Dallas",
                )
            ]
        }
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_UNGROUNDED_OUTPUT"
    assert "target:name" in str(exc.value)
    assert "target:industry" in str(exc.value)
    assert "target:location" in str(exc.value)


def test_target_abbreviation_is_preserved_without_expansion() -> None:
    raw = "Find roofers in NWA."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="market",
                    source_text="roofers in NWA",
                    industry="roofing",
                    location="NWA",
                )
            ]
        }
    )

    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)

    assert intent.target_entities[0].location == "NWA"


def test_target_name_allows_bounded_spelling_repair() -> None:
    raw = "Research alce."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="person",
                    source_text="alce",
                    name="Alice",
                )
            ]
        }
    )

    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)

    assert intent.target_entities[0].name == "Alice"


def test_target_radius_cannot_be_invented_outside_its_source_span() -> None:
    raw = "Find roofers near Austin."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="market",
                    source_text="roofers near Austin",
                    industry="roofing",
                    location="Austin",
                    radius_km=25,
                )
            ]
        }
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_UNGROUNDED_OUTPUT"


def test_contradiction_spans_must_quote_the_instruction() -> None:
    raw = "Draft the message but do not send it."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "contradictions": [
                InterpretationContradiction(
                    field_path="send_policy",
                    first_span="Send it immediately",
                    second_span="do not send it",
                    first_value="send",
                    second_value="do_not_send",
                )
            ]
        }
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_UNGROUNDED_OUTPUT"


def test_target_schema_rejects_arbitrary_attributes_that_could_select_routing() -> None:
    with pytest.raises(ValidationError):
        GroundedTarget.model_validate(
            {
                "type": "market",
                "source_text": "roofers in Austin",
                "industry": "roofing",
                "location": "Austin",
                "attributes": {"research_source": "dangerous.admin_tool"},
            }
        )


def test_context_source_requirement_must_be_allowlisted_and_grounded() -> None:
    raw = "Research Acme Roofing."
    with pytest.raises(ValidationError):
        GroundedContextRequirement.model_validate(
            {
                "requirement": "dangerous_admin_source",
                "source_text": raw,
            }
        )

    candidate = llm_interpretation(raw).model_copy(
        update={
            "context_requirements": [
                GroundedContextRequirement(
                    requirement="hubspot_source",
                    source_text="Use HubSpot as the source",
                )
            ]
        }
    )
    with pytest.raises(MissionInterpreterOutputError) as exc:
        LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert exc.value.code == "INTERPRETER_UNGROUNDED_OUTPUT"


def test_profile_target_must_come_from_approved_profile_context() -> None:
    raw = "Research competitors for my company."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="company",
                    source="profile_context",
                    source_text="Acme Roofing",
                    name="Acme Roofing",
                    domain="acme.example",
                )
            ]
        }
    )
    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(
        raw,
        profile_context={"company": "Acme Roofing", "website": "acme.example"},
    )
    assert intent.target_entities[0].provenance == "profile_context"


def test_low_confidence_execution_detail_requires_restatement() -> None:
    raw = "Find roofers in Austin."
    candidate = llm_interpretation(raw).model_copy(
        update={
            "target_entities": [
                GroundedTarget(
                    type="market",
                    source_text="roofers in Austin",
                    industry="roofing",
                    location="Austin",
                    confidence=0.4,
                )
            ]
        }
    )
    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert intent.interpretation_ready is False
    assert any(item.field == "low_confidence" for item in intent.ambiguity)


def test_non_material_unmatched_segment_does_not_block_readiness() -> None:
    raw = "Please find roofers in Austin."
    candidate = llm_interpretation(
        raw,
        segments=[
            InterpretationSegment(
                source_text="Please",
                normalized_text="Please",
                kind="other",
                material=False,
                accounted=False,
                reason="courtesy word",
            ),
            InterpretationSegment(
                source_text="find roofers in Austin.",
                normalized_text="Find roofing companies in Austin.",
                kind="action",
                material=True,
                accounted=True,
                mapped_outcomes=["research_prospects"],
            ),
        ],
    )
    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert intent.unmatched_material_units == []
    assert intent.interpretation_ready is True


def test_unhandled_material_wording_gets_an_actionable_restatement_question() -> None:
    raw = "Find roofers and do the special thing."
    candidate = llm_interpretation(
        raw,
        segments=[
            InterpretationSegment(
                source_text="Find roofers",
                normalized_text="Find roofing companies",
                kind="action",
                accounted=True,
                mapped_outcomes=["research_prospects"],
            ),
            InterpretationSegment(
                source_text="and do the special thing.",
                normalized_text="and do the special thing.",
                kind="action",
                material=True,
                accounted=False,
                reason="The requested action is not defined.",
            ),
        ],
    )
    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert intent.interpretation_ready is False
    assert any("special thing" in item.question for item in intent.ambiguity)


def test_unsupported_or_contradictory_meaning_cannot_fail_without_user_guidance() -> None:
    raw = "Send the message now, but never send it."
    candidate = llm_interpretation(raw, outcomes=()).model_copy(
        update={
            "unsupported_outcomes": [
                GroundedUnsupportedOutcome(
                    text="perform an unsupported delivery mode",
                    source_text="Send the message now",
                )
            ],
            "contradictions": [
                InterpretationContradiction(
                    field_path="send_policy",
                    first_span="Send the message now",
                    second_span="never send it",
                    first_value="send",
                    second_value="do_not_send",
                )
            ],
        }
    )
    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert intent.interpretation_ready is False
    assert {item.field for item in intent.ambiguity} == {"unsupported_outcomes", "send_policy"}


def test_model_clarification_keeps_interpretation_non_executable() -> None:
    raw = "Handle the prospects."
    candidate = llm_interpretation(raw, outcomes=()).model_copy(
        update={
            "clarifications": [
                InterpretationClarification(
                    field="requested_outcomes",
                    question="What outcome should Ajenda produce for the prospects?",
                    reason="The requested action is ambiguous.",
                )
            ]
        }
    )
    intent = LlmMissionInterpreter(client=StaticMissionInterpreterClient(candidate)).interpret(raw)
    assert intent.interpretation_ready is False
    assert "restatement_required" in intent.interpretation_readiness_reasons


def test_empty_and_oversized_instructions_fail_before_transport() -> None:
    candidate = llm_interpretation("placeholder")
    client = StaticMissionInterpreterClient(candidate)
    interpreter = LlmMissionInterpreter(client=client)

    with pytest.raises(MissionInterpreterOutputError) as empty:
        interpreter.interpret("   ")
    assert empty.value.code == "INSTRUCTION_REQUIRED"

    with pytest.raises(MissionInterpreterOutputError) as oversized:
        interpreter.interpret("x" * 8001)
    assert oversized.value.code == "INSTRUCTION_TOO_LONG"
    assert client.requests == []
