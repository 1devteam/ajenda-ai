"""Guards for Ollama constrained-decoding schema projection."""

from __future__ import annotations

from backend.services.mission_composition.interpretation.schema import LlmMissionInterpretation
from backend.services.mission_composition.interpretation.schema_compat import constrained_decoding_schema


def test_constrained_decoding_schema_inlines_defs_and_drops_breaking_keys() -> None:
    raw = LlmMissionInterpretation.model_json_schema()
    cleaned = constrained_decoding_schema(raw)

    assert "$defs" not in cleaned
    assert "definitions" not in cleaned
    assert cleaned.get("type") == "object"
    assert "interpreted_instruction" in cleaned.get("properties", {})
    assert "segments" in cleaned.get("properties", {})

    dumped = str(cleaned)
    assert "$ref" not in dumped
    assert "minLength" not in dumped
    assert "maxLength" not in dumped
    assert "additionalProperties" not in dumped


def test_constrained_decoding_schema_converts_const_to_enum() -> None:
    cleaned = constrained_decoding_schema(LlmMissionInterpretation.model_json_schema())
    schema_version = cleaned["properties"]["schema_version"]
    assert schema_version.get("enum") == [1]
    assert "const" not in schema_version


def test_nullable_fields_use_type_union_not_anyof_when_possible() -> None:
    cleaned = constrained_decoding_schema(LlmMissionInterpretation.model_json_schema())
    # Walk a known nullable leaf from GroundedTarget (inlined under target_entities.items).
    target_items = cleaned["properties"]["target_entities"]["items"]
    email = target_items["properties"]["email"]
    assert "anyOf" not in email
    email_type = email.get("type")
    if isinstance(email_type, list):
        assert "string" in email_type and "null" in email_type
    else:
        assert email_type == "string"
