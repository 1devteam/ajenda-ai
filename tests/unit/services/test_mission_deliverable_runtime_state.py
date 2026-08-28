import json

import pytest
from pydantic import ValidationError

from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
    load_deliverable_runtime_state,
)


def _request(text: str):
    request = extract_deliverable_request(text)
    assert request is not None
    return request


def test_runtime_state_persists_canonical_request_and_projection_without_authority() -> None:
    state = build_deliverable_runtime_state(
        _request("Return company name, qualification reasons, qualification score, and drafts.")
    )

    assert state is not None
    assert state["schema_version"] == 1
    assert state["grants_execution_authority"] is False
    assert state["completion"] is None
    assert [field["field_key"] for field in state["request"]["fields"]] == [
        "company_name",
        "qualification_reasons",
        "qualification_score",
        "drafts",
    ]
    assert [field["source_text"] for field in state["request"]["fields"]] == [
        "company name",
        "qualification reasons",
        "qualification score",
        "drafts",
    ]
    assert all(field["required"] is True for field in state["request"]["fields"])
    bindings = {item["field_key"]: item for item in state["projection"]["bindings"]}
    assert bindings["company_name"]["status"] == "bound"
    assert bindings["qualification_reasons"]["status"] == "bound"
    assert bindings["qualification_score"]["status"] == "bound"
    assert bindings["drafts"]["status"] == "bound"
    assert json.loads(json.dumps(state)) == state


def test_runtime_state_preserves_unresolved_request_items_fail_closed() -> None:
    state = build_deliverable_runtime_state(_request("Return company name and lunar risk index."))

    assert state is not None
    assert state["request"]["unresolved_items"] == ["lunar risk index"]
    assert state["projection"]["request_unresolved_items"] == ["lunar risk index"]


def test_runtime_state_none_when_instruction_has_no_deliverable_request() -> None:
    assert build_deliverable_runtime_state(None) is None


def test_runtime_state_loader_rejects_forged_execution_authority() -> None:
    state = build_deliverable_runtime_state(_request("Return company name."))
    assert state is not None
    forged = {**state, "grants_execution_authority": True}

    with pytest.raises(ValidationError):
        load_deliverable_runtime_state(forged)


def test_metadata_key_is_explicit_and_stable() -> None:
    assert DELIVERABLE_RUNTIME_STATE_METADATA_KEY == "deliverable_runtime_state"
