"""Unit tests for optional linguistic normalization helpers."""

from __future__ import annotations

from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.interpretation.normalize import normalize_instruction_text
from backend.services.mission_composition.interpretation.spelling import apply_spelling_candidates


def test_builtin_spelling_corrects_competors() -> None:
    text, corrections, components = apply_spelling_candidates("research competors in austin")
    assert "competitors" in text.lower()
    assert any(c.original.lower() == "competors" for c in corrections)
    assert "spelling_builtin" in components


def test_protected_tokens_not_rewritten() -> None:
    text, corrections, _ = apply_spelling_candidates("connect Gmail and HubSpot CRM")
    assert "Gmail" in text or "gmail" in text.lower()
    assert not any(c.original.lower() in {"gmail", "hubspot", "crm"} for c in corrections)


def test_normalize_preserves_urls_and_emails() -> None:
    raw = "Research https://example.com/acme for owner@acme.example competors"
    result = normalize_instruction_text(raw, spelling_enabled=True)
    assert "https://example.com/acme" in result.normalized
    assert "owner@acme.example" in result.normalized
    assert "competitors" in result.normalized.lower()


def test_interpreter_records_spelling_component() -> None:
    intent = interpret_instruction(
        "research roofing companies in austin identify three competors",
        spelling_enabled=True,
        fuzzy_enabled=False,
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "spelling_builtin" in intent.components_active or "regex_core" in intent.components_active


def test_interpreter_works_with_linguistic_helpers_disabled() -> None:
    intent = interpret_instruction(
        "Research three roofing companies in Austin and draft introductions. Do not send.",
        spelling_enabled=False,
        fuzzy_enabled=False,
    )
    assert "research_prospects" in intent.requested_outcomes
    assert "prepare_outreach" in intent.requested_outcomes
    assert intent.send_policy.mode == "forbid"
