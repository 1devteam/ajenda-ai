import json
import subprocess
import sys
from pathlib import Path
from types import FrameType

import pytest
from pydantic import ValidationError

from backend.services.mission_composition.contracts import INTERPRETER_VERSION
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from scripts.validation import shadow_interpreter_trace
from scripts.validation.shadow_interpreter_trace import _ReplayReport, _Trace, replay_interpreter

_REQUEST = "Read up to three accounts from internal CRM. Do not use HubSpot."
_OPTIONS = {"spelling_enabled": False, "fuzzy_enabled": False}


def test_replay_observes_internal_decisions_and_matches_unobserved_intent() -> None:
    expected = interpret_instruction(_REQUEST, **_OPTIONS)
    observed = replay_interpreter(_REQUEST, **_OPTIONS)

    assert observed.intent == expected
    assert observed.error_type is None
    assert observed.capture_errors == observed.dropped_events == 0
    events = observed.report()["events"]
    assert isinstance(events, list)
    assert [item["sequence"] for item in events] == list(range(1, len(events) + 1))
    assert events[0]["function"] == events[-1]["function"] == "interpret_instruction"
    assert events[0]["event"] == "call"
    assert events[-1]["event"] == "return"
    lexical = next(
        item for item in events if item["function"] == "classify_lexical_frame" and item["event"] == "return"
    )
    assert isinstance(lexical["result"], dict)
    assert lexical["result"]["source"] == "internal_crm"
    assert lexical["parent_call"] == events[0]["call"]
    assert any(
        item["event"] == "field_changed" and item["field"] == "hubspot_prohibited" and item["after"] is True
        for item in events
    )
    assert any(
        item["event"] == "field_changed" and item["field"] == "quantity" and item["after"] == 3 for item in events
    )
    assert any(
        item["function"] == "_evidence"
        and item["event"] == "return"
        and isinstance(result := item["result"], dict)
        and result["rule"] == "entity.quantity"
        for item in events
    )


def test_event_limit_preserves_interpreter_result() -> None:
    observed = replay_interpreter(_REQUEST, max_events=3, **_OPTIONS)
    assert len(observed.events) == 3
    assert observed.dropped_events > 0
    assert observed.intent == interpret_instruction(_REQUEST, **_OPTIONS)


def test_capture_exception_preserves_intent_and_restores_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = interpret_instruction(_REQUEST, **_OPTIONS)

    def capture_unavailable(*_: object) -> None:
        raise RuntimeError("capture unavailable")

    monkeypatch.setattr(_Trace, "_record", capture_unavailable)

    def existing_trace(_frame: FrameType, _event: str, _arg: object) -> None:
        return None

    previous = sys.gettrace()
    sys.settrace(existing_trace)
    try:
        observed = replay_interpreter(_REQUEST, **_OPTIONS)
        assert sys.gettrace() is existing_trace
    finally:
        sys.settrace(previous)

    assert observed.intent == expected
    assert observed.capture_errors > 0
    assert observed.error_type is None


def test_trace_install_failure_still_runs_interpreter_once(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = interpret_instruction(_REQUEST, **_OPTIONS)
    attempts = []

    def capture_unavailable(_: object) -> None:
        raise RuntimeError("capture unavailable")

    def run_interpreter(instruction: str, **_: object) -> object:
        attempts.append(instruction)
        return expected

    monkeypatch.setattr(sys, "settrace", capture_unavailable)
    monkeypatch.setattr(shadow_interpreter_trace.intent_interpreter, "interpret_instruction", run_interpreter)
    observed = replay_interpreter(_REQUEST, **_OPTIONS)

    assert attempts == [_REQUEST]
    assert observed.intent == expected
    assert observed.events == []
    assert observed.capture_errors == 1
    assert observed.error_type is None


def test_trace_restore_failure_preserves_intent_and_stops_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = interpret_instruction(_REQUEST, **_OPTIONS)
    original_settrace = sys.settrace
    previous = sys.gettrace()

    def restore_unavailable(callback: object) -> None:
        if callback is previous:
            raise RuntimeError("restore unavailable")
        original_settrace(callback)

    with monkeypatch.context() as patch:
        patch.setattr(sys, "settrace", restore_unavailable)
        try:
            observed = replay_interpreter(_REQUEST, **_OPTIONS)
            event_count = len(observed.events)
            interpret_instruction(_REQUEST, **_OPTIONS)
            assert len(observed.events) == event_count
        finally:
            original_settrace(previous)

    assert observed.intent == expected
    assert event_count > 0
    assert observed.capture_errors == 1
    assert observed.error_type is None


def test_replay_identifies_failure_before_interpretation_hand_off() -> None:
    observed = replay_interpreter(" ", **_OPTIONS)
    report = observed.report()
    assert observed.intent is None
    assert observed.error_type == "ValueError"
    assert report["status"] == "failed"
    assert report["interpreter_version"] == INTERPRETER_VERSION
    events = report["events"]
    assert isinstance(events, list)
    assert [
        (item["event"], item.get("error_type")) for item in events if item["function"] == "interpret_instruction"
    ] == [
        ("call", None),
        ("exception", "ValueError"),
        ("unwind", "ValueError"),
    ]


def test_caught_exception_can_still_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def handled_exception() -> None:
        try:
            raise ValueError("private detail")
        except ValueError:
            pass

    monkeypatch.setattr(shadow_interpreter_trace, "_WATCHED", {handled_exception.__code__})
    trace = _Trace(max_events=10)
    previous = sys.gettrace()
    sys.settrace(trace.trace)
    try:
        handled_exception()
    finally:
        sys.settrace(previous)

    events = [event.model_dump() for event in trace.events]
    assert [event["event"] for event in events] == ["call", "exception", "return"]
    assert events[-1]["result"] == {"value": None}


def test_report_rejects_execution_authority_and_inconsistent_outcome() -> None:
    report = replay_interpreter(_REQUEST, **_OPTIONS).report()

    with pytest.raises(ValidationError, match="grants_execution_authority"):
        _ReplayReport.model_validate({**report, "grants_execution_authority": True})
    with pytest.raises(ValidationError, match="replay status, intent, and interpreter error disagree"):
        _ReplayReport.model_validate({**report, "status": "failed"})


def test_cli_reads_stdin_and_omits_raw_clause_values() -> None:
    program = Path(__file__).resolve().parents[3] / "scripts" / "validation" / "shadow_interpreter_trace.py"
    result = subprocess.run(
        [sys.executable, str(program), "--no-spelling", "--no-fuzzy"],
        input='Find CRM accounts matching "Private Customer Company".',
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1
    assert data["scope"] == "interpreter_replay"
    assert data["authority_class"] == "read_model"
    assert data["grants_execution_authority"] is False
    assert data["status"] == "completed"
    assert data["events"]
    assert "Private Customer Company" not in result.stdout
