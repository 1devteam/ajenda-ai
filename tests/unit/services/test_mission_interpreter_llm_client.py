"""Unit tests for interpreter transport helpers."""

from __future__ import annotations

import json

import pytest

from backend.app.config import Settings
from backend.services.mission_composition.interpretation.llm_client import (
    MissionInterpreterTransportError,
    OpenAiCompatibleMissionInterpreterClient,
    _coerce_structural_defaults,
    _extract_json_payload,
    _response_content,
)
from backend.services.mission_composition.interpretation.schema import LlmMissionInterpretation


def test_extract_json_payload_accepts_raw_object() -> None:
    assert _extract_json_payload('{"schema_version": 1}') == '{"schema_version": 1}'


def test_extract_json_payload_strips_markdown_fence() -> None:
    fenced = """```json
{"schema_version": 1, "interpreted_instruction": "Find 3 roofers"}
```"""
    assert json.loads(_extract_json_payload(fenced))["interpreted_instruction"] == "Find 3 roofers"


def test_extract_json_payload_pulls_object_from_prose_wrapper() -> None:
    wrapped = 'Here you go:\n{"schema_version": 1}\nThanks'
    assert _extract_json_payload(wrapped) == '{"schema_version": 1}'


def test_response_content_requires_nonempty_message() -> None:
    with pytest.raises(ValueError, match="empty"):
        _response_content({"choices": [{"message": {"content": "   "}}]})


def test_disabled_client_fails_closed() -> None:
    settings = Settings(
        mission_interpreter_enabled=False,
        mission_interpreter_base_url="http://127.0.0.1:11434/v1",
        mission_interpreter_model="llama3.2:latest",
    )
    client = OpenAiCompatibleMissionInterpreterClient(settings=settings)
    with pytest.raises(MissionInterpreterTransportError) as exc:
        client.interpret(
            type("Req", (), {"system_prompt": "s", "user_prompt": "u"})()  # type: ignore[arg-type]
        )
    assert exc.value.code == "INTERPRETER_DISABLED"


def test_coerce_accepts_live_qwen_shape_with_string_schema_and_aliases() -> None:
    """Structural coerce must accept common Ollama json_object shape without inventing facts."""

    payload = {
        "schema_version": "1",
        "interpreted_instruction": (
            "Find five residential roofing contractors in Austin, Texas, and draft an "
            "outreach email without sending it."
        ),
        "requested_outcomes": [
            {
                "outcome": "research_prospects",
                "source_text": "Find 5 residential roofing contractors in Austin Texas.",
            },
            {
                "outcome": "write_crm_record",
                "source_text": "Draft an outreach email but do not send it.",
            },
            {
                "outcome": "collect_context",
                "source_text": "Success: a shortlist of 5 contractors with company name and website.",
            },
        ],
        "send_policy": {"mode": "forbid"},
        "target_entities": [
            {
                "type": "company",
                "source_text": "residential roofing contractors in Austin Texas",
                "location": "Austin, Texas",
                "industry": "residential roofing",
            }
        ],
        "requested_quantity": 5,
        "quantity_source_text": "Find 5 residential roofing contractors in Austin Texas.",
        "success_criteria": {
            "description": "A shortlist of 5 contractors with company name and website.",
            "source_text": "Success: a shortlist of 5 contractors with company name and website.",
        },
        "segments": [
            {
                "source_text": "Find 5 residential roofing contractors in Austin Texas.",
                "normalized_text": "residential roofing contractors in Austin Texas",
            },
            {
                "source_text": "Draft an outreach email but do not send it.",
                "normalized_text": "draft outreach email without sending",
            },
        ],
    }
    coerced = _coerce_structural_defaults(payload)
    model = LlmMissionInterpretation.model_validate(coerced)
    assert model.schema_version == 1
    assert [item.outcome for item in model.requested_outcomes] == [
        "research_prospects",
        "prepare_outreach",
    ]
    assert model.send_policy.mode == "forbid"
    assert model.send_policy.source_text
    assert model.requested_quantity == 5
    assert "collect_context" in {item.text for item in model.unsupported_outcomes}


def test_coerce_maps_location_target_and_quantity_source() -> None:
    payload = {
        "interpreted_instruction": "Find 10 roofing contractors in Austin. Do not send email.",
        "requested_outcomes": [{"outcome": "research_prospects"}],
        "send_policy": {"mode": "forbid"},
        "target_entities": [{"type": "location", "value": "Austin"}],
        "requested_quantity": 10,
        "success_criteria": [{"description": "list of contractors"}],
    }
    model = LlmMissionInterpretation.model_validate(_coerce_structural_defaults(payload))
    assert model.target_entities[0].type == "market"
    assert model.target_entities[0].location == "Austin"
    assert model.target_entities[0].source_text
    assert model.quantity_source_text
    assert "10" in model.quantity_source_text or model.quantity_source_text == model.interpreted_instruction
    assert model.success_criteria[0].source_text == "list of contractors"


def test_coerce_maps_do_not_policy_mode_to_forbid() -> None:
    payload = {
        "schema_version": 1,
        "interpreted_instruction": "Find 5 contractors. Draft email but do not send it.",
        "requested_outcomes": [
            {"outcome": "research_prospects", "source_text": "Find 5 contractors"},
            {"outcome": "prepare_outreach", "source_text": "Draft email but do not send it"},
        ],
        "send_policy": {"mode": "do_not", "source_text": "do not send it"},
        "target_entities": [{"type": "company", "source_text": "contractors", "location": "Austin"}],
        "requested_quantity": 5,
        "quantity_source_text": "Find 5",
        "success_criteria": [{"description": "shortlist", "source_text": "shortlist"}],
        "segments": [
            {"source_text": "Find 5 contractors", "normalized_text": "Find 5 contractors"},
            {"source_text": "Draft email but do not send it", "normalized_text": "Draft email but do not send it"},
        ],
    }
    model = LlmMissionInterpretation.model_validate(_coerce_structural_defaults(payload))
    assert model.send_policy.mode == "forbid"
    assert model.send_policy.source_text == "do not send it"


def test_coerce_recovers_segment_actions_and_forbid_language() -> None:
    """json_object free-form: segment.action + do-not-send text, no schema extras."""

    payload = {
        "interpreted_instruction": (
            "research_prospects: Find 5 roofing contractors in Austin. "
            "prepare_outreach: Draft email but do not send."
        ),
        "requested_quantity": 5,
        "quantity_source_text": "Find 5",
        "segments": [
            {
                "source_text": "Find 5 roofing contractors in Austin",
                "action": "research_prospects",
                "target": "roofing contractors in Austin",
                "accounted": True,
            },
            {
                "source_text": "Draft email but do not send",
                "action": "prepare_outreach",
                "target": "email",
                "constraint": "do not send",
                "accounted": True,
            },
        ],
        "confidence": 0.99,
        "mode": "unknown",
    }
    model = LlmMissionInterpretation.model_validate(_coerce_structural_defaults(payload))
    assert [item.outcome for item in model.requested_outcomes] == [
        "research_prospects",
        "prepare_outreach",
    ]
    assert model.send_policy.mode == "forbid"
    assert model.send_policy.source_text
    assert model.requested_quantity == 5
    assert all(t.location != "email" for t in model.target_entities)
