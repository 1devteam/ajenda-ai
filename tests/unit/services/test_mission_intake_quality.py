from __future__ import annotations

import pytest

from backend.services.mission_intake_quality import (
    MissionIntakeQualityDeniedError,
    validate_mission_intake_prompt,
)


def _valid_criterion() -> dict[str, object]:
    return {
        "description": "Every stale qualified opportunity has a documented recommended next action.",
        "evidence": ["opportunity review summary"],
    }


def test_validate_accepts_concrete_mission_prompt() -> None:
    validate_mission_intake_prompt(
        objective="Recover qualified inbound opportunities that have not received follow-up within 14 days.",
        success_criteria=[_valid_criterion()],
    )


def test_validate_denies_placeholder_objective() -> None:
    with pytest.raises(MissionIntakeQualityDeniedError) as exc_info:
        validate_mission_intake_prompt(
            objective="do something",
            success_criteria=[_valid_criterion()],
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "objective_placeholder" in codes


def test_validate_denies_vague_success_criterion() -> None:
    with pytest.raises(MissionIntakeQualityDeniedError) as exc_info:
        validate_mission_intake_prompt(
            objective="Research enterprise roofing prospects in Texas and identify qualified opportunities.",
            success_criteria=[{"description": "be successful", "evidence": []}],
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "success_criterion_too_vague" in codes


def test_validate_denies_non_measurable_success_criterion() -> None:
    with pytest.raises(MissionIntakeQualityDeniedError) as exc_info:
        validate_mission_intake_prompt(
            objective="Research enterprise roofing prospects in Texas and identify qualified opportunities.",
            success_criteria=[{"description": "outcome should feel right", "evidence": []}],
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "success_criterion_not_measurable" in codes


def test_validate_allows_legacy_v1_bypass() -> None:
    validate_mission_intake_prompt(
        objective="test",
        success_criteria=[{"description": "done", "evidence": []}],
        allow_legacy_v1=True,
    )


def test_validate_denies_objective_without_scope_signal() -> None:
    with pytest.raises(MissionIntakeQualityDeniedError) as exc_info:
        validate_mission_intake_prompt(
            objective="Investigate workflows thoroughly and prepare concise summary notes.",
            success_criteria=[_valid_criterion()],
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "objective_lacks_scope_signal" in codes


def test_validate_denies_duplicate_success_criteria() -> None:
    criterion = _valid_criterion()
    with pytest.raises(MissionIntakeQualityDeniedError) as exc_info:
        validate_mission_intake_prompt(
            objective="Find three qualified roofing leads in Austin and draft greeting emails for each prospect.",
            success_criteria=[criterion, criterion],
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "success_criterion_duplicate" in codes


def test_validate_denies_placeholder_allowed_action() -> None:
    with pytest.raises(MissionIntakeQualityDeniedError) as exc_info:
        validate_mission_intake_prompt(
            objective="Find three qualified roofing leads in Austin and draft greeting emails for each prospect.",
            success_criteria=[_valid_criterion()],
            allowed_actions=["whatever"],
        )

    codes = {item.code for item in exc_info.value.violations}
    assert "allowed_action_placeholder" in codes


def test_denied_error_detail_is_structured() -> None:
    try:
        validate_mission_intake_prompt(
            objective="help me",
            success_criteria=[{"description": "success", "evidence": []}],
        )
    except MissionIntakeQualityDeniedError as exc:
        detail = exc.to_detail()
    else:
        raise AssertionError("expected denial")

    assert detail["code"] == "MISSION_INTAKE_QUALITY_DENIED"
    assert detail["schema_version"] == 2
    assert detail["violations"]
    assert detail["violations"][0]["field"] == "objective"
