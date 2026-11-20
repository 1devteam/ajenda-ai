#!/usr/bin/env python3
"""Replay Ajenda's interpreter and show its decisions from outside mission execution."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import FrameType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.mission_composition import intent_interpreter
from backend.services.mission_composition.ability_vocab import match_outcome_phrases
from backend.services.mission_composition.contracts import InterpretationEvidence, MissionIntent, SendPolicy
from backend.services.mission_composition.interpretation import rule_engine
from backend.services.mission_composition.interpretation.fuzzy import fuzzy_outcome_candidates
from backend.services.mission_composition.interpretation.lexical import LexicalFrame, classify_lexical_frame
from backend.services.mission_composition.interpretation.normalize import (
    NormalizationResult,
    normalize_instruction_text,
)
from backend.services.mission_composition.interpretation.outcome_proposer import validate_outcome_proposal
from backend.services.runtime_information_observation import safe_decision_keys

_WATCHED = {
    operation.__code__
    for operation in (
        intent_interpreter.interpret_instruction,
        normalize_instruction_text,
        classify_lexical_frame,
        match_outcome_phrases,
        fuzzy_outcome_candidates,
        validate_outcome_proposal,
        intent_interpreter._extract_recommendation_count,
        intent_interpreter._extract_named_report_company,
        rule_engine._segment_clauses,
        rule_engine._classify_clause,
        rule_engine._extract_target_entities,
        rule_engine._extract_connector_company,
        rule_engine._extract_count,
        rule_engine._extract_qualification_count,
        rule_engine._evidence,
        rule_engine.research_quantity_is_upper_bound,
    )
}
_LINE_WATCHED = {intent_interpreter.interpret_instruction.__code__, rule_engine._classify_clause.__code__}
_DECISION_FLAGS = frozenset(
    {
        "hubspot_prohibited",
        "hubspot_as_research_source",
        "hubspot_as_source",
        "hubspot_write_targeted",
        "internal_crm_requested",
        "external_action_forbidden",
        "recognized",
        "material",
    }
)
_LIST_FIELDS = frozenset({"outcomes", "forbidden_actions", "forbidden_canonical", "context_requirements"})
_QUANTITY_FIELDS = frozenset({"count", "quantity", "qualification_count", "recommendation_count"})
_QUANTITY_PROVENANCE = {"explicit", "inferred_deterministic", "system_default"}
_EventCallback = Callable[[FrameType, str, Any], Any]


def _keys(values: Sequence[str]) -> list[str]:
    return safe_decision_keys(list(values[:80]), limit=80)


def _decision_values(frame: FrameType) -> dict[str, object]:
    """Copy only decision fields, without clause text or arbitrary locals."""
    snapshot: dict[str, object] = {}
    for name, value in frame.f_locals.items():
        if (name.startswith("wants_") or name in _DECISION_FLAGS) and isinstance(value, bool):
            snapshot[name] = value
        elif name in _QUANTITY_FIELDS and (value is None or type(value) is int):
            snapshot[name] = value
        elif name == "quantity_provenance" and (
            value is None or (isinstance(value, str) and value in _QUANTITY_PROVENANCE)
        ):
            snapshot[name] = value
        elif name in _LIST_FIELDS and isinstance(value, list) and all(isinstance(item, str) for item in value):
            snapshot[name] = _keys(value)
        elif name == "send_policy" and isinstance(value, SendPolicy):
            snapshot[name] = {"mode": value.mode, "condition": value.condition, "source": value.source}
    return snapshot


def _intent_summary(intent: MissionIntent) -> dict[str, object]:
    return {
        "requested_outcomes": _keys(intent.requested_outcomes),
        "requested_quantity": intent.requested_quantity,
        "quantity_provenance": intent.quantity_provenance,
        "context_requirements": _keys(intent.context_requirements),
        "forbidden_actions": _keys(intent.forbidden_actions),
        "interpretation_ready": intent.interpretation_ready,
        "clauses": [
            {
                "clause_id": clause.clause_id,
                "material": clause.material,
                "status": clause.status,
                "mapped_outcomes": _keys(clause.mapped_outcomes),
            }
            for clause in intent.interpreted_clauses
        ],
    }


def _result_summary(name: str, result: object) -> dict[str, object]:
    if isinstance(result, NormalizationResult):
        return {
            "components_active": _keys(result.components_active),
            "text_changed": result.original != result.normalized,
            "spelling_correction_count": len(result.spelling_corrections),
        }
    if isinstance(result, LexicalFrame):
        return asdict(result)
    if isinstance(result, InterpretationEvidence):
        fields = _keys([result.field_path])
        rule = _keys([result.rule_id])[0] if result.rule_id else None
        return {"field": fields[0], "source": result.source, "rule": rule, "confidence": result.confidence}
    if isinstance(result, MissionIntent):
        return _intent_summary(result)
    if name == "_classify_clause" and isinstance(result, tuple):
        outcomes, material, recognized = result
        return {"outcomes": _keys(outcomes), "material": material, "recognized": recognized}
    if isinstance(result, list):
        return {"item_count": len(result)}
    if result is None or isinstance(result, (bool, int)):
        return {"value": result}
    return {"type": type(result).__name__}


@dataclass
class _Call:
    number: int
    parent: int | None
    last_line: int
    values: dict[str, object] = field(default_factory=dict)


@dataclass
class _Trace:
    max_events: int
    events: list[dict[str, object]] = field(default_factory=list)
    dropped_events: int = 0
    capture_errors: int = 0
    _calls: dict[int, _Call] = field(default_factory=dict)
    _next_call: int = 0

    def _record(self, frame: FrameType, call: _Call, event: str, details: dict[str, object]) -> None:
        if len(self.events) >= self.max_events:
            self.dropped_events += 1
            return
        self.events.append(
            {
                "sequence": len(self.events) + 1,
                "event": event,
                "call": call.number,
                "parent_call": call.parent,
                "function": frame.f_code.co_name,
                "source": str(frame.f_globals["__name__"]).replace(".", "/") + ".py",
                "line": call.last_line if event == "field_changed" else frame.f_lineno,
                **details,
            }
        )

    def _trace(self, frame: FrameType, event: str, arg: Any) -> _EventCallback | None:
        frame_id = id(frame)
        if event == "call":
            if frame.f_code not in _WATCHED:
                return None
            parent = frame.f_back
            while parent is not None and id(parent) not in self._calls:
                parent = parent.f_back
            self._next_call += 1
            started = _Call(
                self._next_call, self._calls[id(parent)].number if parent is not None else None, frame.f_lineno
            )
            self._calls[frame_id] = started
            frame.f_trace_lines = frame.f_code in _LINE_WATCHED
            self._record(frame, started, "call", {})
            return self.trace

        call = self._calls.get(frame_id)
        if call is None:
            return None
        if frame.f_trace_lines and event in {"line", "return", "exception"}:
            values = _decision_values(frame)
            for name, current in values.items():
                if name not in call.values or call.values[name] != current:
                    self._record(
                        frame,
                        call,
                        "field_changed",
                        {
                            "field": name,
                            "before_present": name in call.values,
                            "before": call.values.get(name),
                            "after": current,
                        },
                    )
            call.values = values
            call.last_line = frame.f_lineno
        if event == "exception":
            self._record(frame, call, "exception", {"error_type": arg[0].__name__})
        elif event == "return":
            self._calls.pop(frame_id)
            self._record(frame, call, "return", {"result": _result_summary(frame.f_code.co_name, arg)})
        return self.trace

    def trace(self, frame: FrameType, event: str, arg: Any) -> _EventCallback | None:
        try:
            return self._trace(frame, event, arg)
        except Exception:
            # A trace-formatting problem cannot become an interpreter exception.
            self.capture_errors += 1
            self._calls.pop(id(frame), None)
            return None


@dataclass(frozen=True)
class InterpreterReplay:
    intent: MissionIntent | None
    events: list[dict[str, object]]
    dropped_events: int
    capture_errors: int
    error_type: str | None

    def report(self) -> dict[str, object]:
        return {
            "scope": "interpreter_replay",
            "interpreter_version": self.intent.interpreter_version if self.intent else None,
            "status": "completed" if self.intent is not None else "failed",
            "intent": _intent_summary(self.intent) if self.intent is not None else None,
            "events": self.events,
            "dropped_events": self.dropped_events,
            "capture_errors": self.capture_errors,
            "error_type": self.error_type,
        }


def replay_interpreter(
    instruction: str,
    *,
    profile_context: dict[str, Any] | None = None,
    business_need_assessment_available: bool = False,
    spelling_enabled: bool | None = None,
    fuzzy_enabled: bool | None = None,
    max_events: int = 1000,
) -> InterpreterReplay:
    """Run the production interpreter under a temporary, opt-in Python trace."""
    if max_events < 1:
        raise ValueError("max_events must be positive")
    trace = _Trace(max_events=max_events)
    previous = sys.gettrace()
    intent: MissionIntent | None = None
    error_type: str | None = None
    try:
        sys.settrace(trace.trace)
        intent = intent_interpreter.interpret_instruction(
            instruction,
            profile_context=profile_context,
            business_need_assessment_available=business_need_assessment_available,
            spelling_enabled=spelling_enabled,
            fuzzy_enabled=fuzzy_enabled,
        )
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        sys.settrace(previous)
    return InterpreterReplay(intent, trace.events, trace.dropped_events, trace.capture_errors, error_type)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruction-file", type=Path, help="Read the mission request from a file instead of stdin")
    parser.add_argument("--profile-context", type=Path, help="JSON object supplied as interpreter profile context")
    parser.add_argument("--business-need-assessment-available", action="store_true")
    parser.add_argument("--spelling", action=argparse.BooleanOptionalAction)
    parser.add_argument("--fuzzy", action=argparse.BooleanOptionalAction)
    parser.add_argument("--max-events", type=int, default=1000)
    args = parser.parse_args()
    try:
        instruction = args.instruction_file.read_text(encoding="utf-8") if args.instruction_file else sys.stdin.read()
        context = json.loads(args.profile_context.read_text(encoding="utf-8")) if args.profile_context else None
        if args.profile_context and not isinstance(context, dict):
            parser.error("profile context must be a JSON object")
        replay = replay_interpreter(
            instruction,
            profile_context=context,
            business_need_assessment_available=args.business_need_assessment_available,
            spelling_enabled=args.spelling,
            fuzzy_enabled=args.fuzzy,
            max_events=args.max_events,
        )
    except (OSError, ValueError) as exc:
        parser.error(f"unable to configure replay ({type(exc).__name__})")
    print(json.dumps(replay.report(), indent=2))
    return 0 if replay.intent is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
