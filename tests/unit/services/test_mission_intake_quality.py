from __future__ import annotations

import pytest

from backend.services.mission_intake_quality import (
    MissionIntakeQualityDeniedError,
    contains_composition_clarification,
    validate_mission_intake_prompt,
)


def _valid_criterion() -> dict[str, object]:
    return {
        "description": "Every stale qualified opportunity has a documented recommended next action.",
        "evidence": ["opportunity review summary"],
    }


def test_composition_clarification_context_is_not_a_mission_instruction() -> None:
    assert contains_composition_clarification(
        {
            "composition": {
                "instruction": (
                    "Restate the complete mission. I cannot compose this mission reliably because the requested outcome was unclear."
                )
            }
        }
    )
    assert not contains_composition_clarification({"composition": {"instruction": "Find three qualified leads."}})


def test_validate_accepts_concrete_mission_prompt() -> None:
    validate_mission_intake_prompt(
        objective="Recover qualified inbound opportunities that have not received follow-up within 14 days.",
        success_criteria=[_valid_criterion()],
    )


def test_validate_accepts_bounded_internal_crm_records_mission() -> None:
    validate_mission_intake_prompt(
        objective=(
            "Use Ajenda internal CRM records, qualify the strongest three, and draft introductions. Do not send."
        ),
        success_criteria=[
            {
                "description": "3 prospects contain company and qualification evidence for CRM records",
                "evidence": ["qualified_prospects artifact"],
            },
            {
                "description": "3 personalized introduction drafts are ready for review",
                "evidence": ["introduction_drafts artifact"],
            },
        ],
        allowed_actions=["record.search", "sales.qualify", "gtm.email_draft"],
    )


@pytest.mark.parametrize(
    "objective",
    [
        "Read three plumbing companies in Austin from internal CRM.",
        "Read three HVAC companies in Dallas from internal CRM.",
    ],
)
def test_validate_accepts_natural_internal_crm_read_verbs_without_location_bias(objective: str) -> None:
    validate_mission_intake_prompt(
        objective=objective,
        success_criteria=[
            {
                "description": "Requested CRM records are returned with source evidence",
                "evidence": ["crm_records artifact"],
            }
        ],
        scope_limits=["the requested companies only"],
        allowed_actions=["record.search"],
    )


def test_validate_accepts_short_explicit_safety_constraint() -> None:
    validate_mission_intake_prompt(
        objective=("Observe the web page at https://example.com and return its title and visible text."),
        success_criteria=[
            {
                "description": "A web_page_observation artifact records the observed page and evidence.",
                "evidence": ["web_page_observation artifact"],
            }
        ],
        constraints=[{"name": "No outbound messages", "description": "Do not send messages", "hard": True}],
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


def test_validate_allows_explicit_url_as_web_observation_scope() -> None:
    validate_mission_intake_prompt(
        objective=(
            "Observe https://example.com using a read-only browser session and extract the page title and visible body text."
        ),
        success_criteria=[
            {
                "description": (
                    "A web_page_observation artifact records the requested URL, final URL, title, visible body text, "
                    "and browser step evidence"
                ),
                "evidence": ["web page observation artifact and browser step trace"],
            }
        ],
    )


def test_validate_allows_observe_page_artifact_without_market_language() -> None:
    validate_mission_intake_prompt(
        objective="Observe the web page at https://example.com and return its title and visible text.",
        success_criteria=[
            {
                "description": (
                    "A web_page_observation artifact records the requested URL, final URL, title, visible body text, "
                    "and browser step evidence with satisfied observation requirements"
                ),
                "evidence": ["web_page_observation artifact"],
            }
        ],
    )


def test_validate_allows_bounded_browser_navigation_objective() -> None:
    validate_mission_intake_prompt(
        objective=("Open https://example.com, navigate to the page, and return the final title and URL."),
        success_criteria=[
            {
                "description": (
                    "A web_page_observation artifact records the final URL, title, and browser step evidence."
                ),
                "evidence": ["web page observation artifact and browser step trace"],
            }
        ],
        constraints=[{"name": "No outbound messages", "description": "Do not send messages", "hard": True}],
    )


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
