import json
import subprocess
import sys
from pathlib import Path
from types import FrameType

import pytest

from backend.services.mission_composition.intent_interpreter import interpret_instruction
from scripts.validation.shadow_interpreter_trace import _Trace, replay_interpreter

_REQUEST = "Read up to three accounts from internal CRM. Do not use HubSpot."
_OPTIONS = {"spelling_enabled": False, "fuzzy_enabled": False}


def test_replay_observes_internal_decisions_and_matches_unobserved_intent() -> None:
    expected = interpret_instruction(_REQUEST, **_OPTIONS)
    observed = replay_interpreter(_REQUEST, **_OPTIONS)

    assert observed.intent == expected
    assert observed.error_type is None
    assert observed.capture_errors == observed.dropped_events == 0
    assert [item["sequence"] for item in observed.events] == list(range(1, len(observed.events) + 1))
    assert observed.events[0]["function"] == observed.events[-1]["function"] == "interpret_instruction"
    assert observed.events[0]["event"] == "call"
    assert observed.events[-1]["event"] == "return"
    lexical = next(
        item for item in observed.events if item["function"] == "classify_lexical_frame" and item["event"] == "return"
    )
    assert isinstance(lexical["result"], dict)
    assert lexical["result"]["source"] == "internal_crm"
    assert lexical["parent_call"] == observed.events[0]["call"]
    assert any(
        item["event"] == "field_changed" and item["field"] == "hubspot_prohibited" and item["after"] is True
        for item in observed.events
    )
    assert any(
        item["event"] == "field_changed" and item["field"] == "quantity" and item["after"] == 3
        for item in observed.events
    )
    assert any(
        item["function"] == "_evidence"
        and item["event"] == "return"
        and isinstance(result := item["result"], dict)
        and result["rule"] == "entity.quantity"
        for item in observed.events
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


def test_replay_identifies_failure_before_interpretation_hand_off() -> None:
    observed = replay_interpreter(" ", **_OPTIONS)
    assert observed.intent is None
    assert observed.report()["status"] == "failed"
    assert observed.error_type == "ValueError"
    assert any(
        item["function"] == "interpret_instruction"
        and item["event"] == "exception"
        and item["error_type"] == "ValueError"
        for item in observed.events
    )


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
    assert data["scope"] == "interpreter_replay"
    assert data["status"] == "completed"
    assert data["events"]
    assert "Private Customer Company" not in result.stdout
