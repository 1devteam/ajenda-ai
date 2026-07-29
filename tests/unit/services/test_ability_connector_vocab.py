"""Ability vocab + connector capability schema for composition."""

from __future__ import annotations

from backend.services.mission_composition.ability_vocab import match_outcome_phrases, phrase_maps_to_outcome
from backend.services.mission_composition.connector_capabilities import (
    connector_defers_op,
    connector_supports_op,
    restatement_for_deferred_op,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction


def test_score_them_maps_to_qualify() -> None:
    assert phrase_maps_to_outcome("score them") == "qualify_prospects"
    hits = match_outcome_phrases("score them and prepare drafts")
    assert any(h.outcome == "qualify_prospects" for h in hits)


def test_score_them_mission_composes_ready() -> None:
    intent = interpret_instruction(
        "Research five competitors of Acme Roofing in Northwest Arkansas, "
        "score them, and prepare outreach drafts for the top three."
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "qualify_prospects" in intent.requested_outcomes
    assert "prepare_outreach" in intent.requested_outcomes
    assert intent.unmatched_material_clauses == []
    assert not any(c.field == "clause_coverage" for c in intent.ambiguity)
    assert intent.interpretation_ready is True
    assert intent.coverage_score >= 0.99


def test_rank_and_best_also_qualify() -> None:
    intent = interpret_instruction(
        "Find five roofing companies in Austin, rank the strongest, and prepare draft emails for review."
    )
    assert "qualify_prospects" in intent.requested_outcomes


def test_calendar_write_uses_connector_schema_not_unknown_phrase() -> None:
    intent = interpret_instruction("Schedule a meeting with Bob tomorrow at 2pm on my calendar.")
    assert "read_calendar" not in intent.requested_outcomes
    assert any(c.field == "calendar_write" for c in intent.ambiguity)
    assert not any(c.field == "requested_outcomes" for c in intent.ambiguity)
    text = " ".join(c.question for c in intent.ambiguity).lower()
    assert "google calendar" in text or "write" in text
    assert "runtime-bound" in text or "read" in text


def test_connector_capability_calendar_defers_write() -> None:
    assert connector_supports_op("google_calendar", "read") is True
    assert connector_supports_op("google_calendar", "write") is False
    assert connector_defers_op("google_calendar", "write") is True
    note = restatement_for_deferred_op(connector_id="google_calendar", op="write")
    assert note is not None
    assert "write" in note.lower()
