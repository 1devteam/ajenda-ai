from __future__ import annotations

import pytest

from backend.services.operating_charter import (
    OperatingCharterViolation,
    assert_action_allowed,
    charter_requires_human_review_for_launch,
    default_operating_charter,
    load_operating_charter,
    parse_operating_charter_fact,
)
from backend.services.tools.schemas import SideEffectClass


def test_default_charter_allows_brain_prepare_actions() -> None:
    charter = default_operating_charter()
    assert_action_allowed(
        action_name="retrieval.hybrid_search",
        side_effect_class=SideEffectClass.NONE,
        charter=charter,
    )
    assert_action_allowed(
        action_name="gtm.crm_upsert",
        side_effect_class=SideEffectClass.INTERNAL_WRITE,
        charter=charter,
    )
    assert_action_allowed(
        action_name="gtm.email_check",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        charter=charter,
    )
    assert_action_allowed(
        action_name="google_calendar.events_read",
        side_effect_class=SideEffectClass.EXTERNAL_READ,
        charter=charter,
    )


def test_default_charter_blocks_external_send() -> None:
    charter = default_operating_charter()
    with pytest.raises(OperatingCharterViolation) as exc:
        assert_action_allowed(
            action_name="gtm.email_send",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            charter=charter,
        )
    assert exc.value.code == "CHARTER_NEVER_DO"


def test_parse_charter_fact_from_profile_value_wrapper() -> None:
    charter = parse_operating_charter_fact(
        {
            "value": {
                "schema_version": 1,
                "may_prepare": ["retrieval.hybrid_search"],
                "may_perform": ["record.write"],
                "never_do": ["gtm.email_send"],
                "approval_mode": "none",
                "escalation_email": "ops@example.com",
            }
        }
    )
    assert charter is not None
    assert charter.source == "profile"
    assert charter.escalation_email == "ops@example.com"
    assert charter.may_prepare == ("retrieval.hybrid_search",)


def test_load_operating_charter_falls_back_to_default() -> None:
    charter = load_operating_charter(approved_facts={})
    assert charter.source == "default"


def test_empty_may_perform_blocks_crm_upsert() -> None:
    charter = parse_operating_charter_fact(
        {
            "schema_version": 1,
            "may_prepare": ["retrieval.hybrid_search"],
            "may_perform": [],
            "never_do": [],
            "approval_mode": "none",
        }
    )
    assert charter is not None
    assert charter.may_perform == ()
    with pytest.raises(OperatingCharterViolation) as exc:
        assert_action_allowed(
            action_name="gtm.crm_upsert",
            side_effect_class=SideEffectClass.INTERNAL_WRITE,
            charter=charter,
        )
    assert exc.value.code == "CHARTER_PERFORM_NOT_ALLOWED"


def test_empty_may_prepare_preserves_explicit_empty_list() -> None:
    charter = parse_operating_charter_fact(
        {
            "schema_version": 1,
            "may_prepare": [],
            "may_perform": ["record.write"],
            "never_do": [],
            "approval_mode": "none",
        }
    )
    assert charter is not None
    assert charter.may_prepare == ()


def test_charter_requires_human_review_for_external_perform() -> None:
    charter = default_operating_charter()
    assert charter_requires_human_review_for_launch(
        charter=charter,
        side_effect_class=SideEffectClass.EXTERNAL_SEND,
    )
    assert not charter_requires_human_review_for_launch(
        charter=charter,
        side_effect_class=SideEffectClass.NONE,
    )


def test_custom_charter_blocks_unlisted_prepare_action() -> None:
    charter = parse_operating_charter_fact(
        {
            "schema_version": 1,
            "may_prepare": ["sales.qualify"],
            "may_perform": [],
            "never_do": [],
            "approval_mode": "none",
        }
    )
    assert charter is not None
    with pytest.raises(OperatingCharterViolation) as exc:
        assert_action_allowed(
            action_name="retrieval.hybrid_search",
            side_effect_class=SideEffectClass.NONE,
            charter=charter,
        )
    assert exc.value.code == "CHARTER_PREPARE_NOT_ALLOWED"
