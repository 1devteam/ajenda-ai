import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.services.mission_composition.coverage import assess_coverage
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    DeliverableArtifactLifecycle,
    build_deliverable_runtime_state,
    load_deliverable_runtime_state,
)
from backend.services.mission_composition.epistemic import build_epistemic_context
from backend.services.mission_composition.intent_interpreter import interpret_instruction


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


def test_new_runtime_state_starts_planned_and_has_no_authority() -> None:
    state = build_deliverable_runtime_state(_request("Return company name."))

    assert state is not None
    assert state["lifecycle"]["state"] == "planned"
    assert state["lifecycle"]["grants_execution_authority"] is False


def test_runtime_state_records_epistemic_reconciliation_snapshot() -> None:
    instruction = (
        "Find five software development companies in Austin using local fixture data only and return company name."
    )
    intent = interpret_instruction(instruction)
    context = build_epistemic_context(intent, assess_coverage(intent))
    state = build_deliverable_runtime_state(_request(instruction), epistemic_context=context)

    assert state is not None
    lifecycle = state["lifecycle"]
    assert lifecycle["epistemic_context_schema_version"] == context.schema_version
    assert lifecycle["epistemic_freshness"] == context.freshness
    assert lifecycle["epistemic_reconciliation"] == "aligned"
    assert lifecycle["epistemic_missing_evidence"] == []


def test_runtime_state_records_coverage_reconciliation_snapshot() -> None:
    instruction = (
        "Find five software development companies in Austin using local fixture data only and return company name."
    )
    intent = interpret_instruction(instruction)
    coverage = assess_coverage(intent)
    state = build_deliverable_runtime_state(
        _request(instruction), coverage_assessment=coverage, epistemic_context=build_epistemic_context(intent, coverage)
    )

    assert state is not None
    lifecycle = state["lifecycle"]
    assert lifecycle["coverage_assessment"] == coverage.model_dump(mode="json")
    assert lifecycle["coverage_assessment"]["grants_execution_authority"] is False
    assert lifecycle["graph_lineage"]["semantic_owner"] == "mission_composition.semantic_vocabulary"
    assert lifecycle["graph_lineage"]["operational_owner"] == "mission_composition.plan_compiler"


def test_lifecycle_effective_state_detects_expired_current_observation() -> None:
    lifecycle = DeliverableArtifactLifecycle(
        state="current",
        observed_at=datetime.now(UTC) - timedelta(days=2),
        freshness_window_seconds=86_400,
    )

    assert lifecycle.effective_state() == "stale"
