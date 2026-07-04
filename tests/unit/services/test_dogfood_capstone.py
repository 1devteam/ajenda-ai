from __future__ import annotations

import pytest

from backend.services.operating_charter import (
    OperatingCharterViolation,
    assert_action_allowed,
    default_operating_charter,
    dogfood_operating_charter,
    load_operating_charter,
)
from backend.services.tools.schemas import SideEffectClass


def test_default_charter_blocks_email_send() -> None:
    charter = default_operating_charter()
    with pytest.raises(OperatingCharterViolation) as exc:
        assert_action_allowed(
            action_name="gtm.email_send",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            charter=charter,
        )
    assert exc.value.code == "CHARTER_NEVER_DO"


def test_dogfood_charter_allows_email_send() -> None:
    charter = dogfood_operating_charter()
    assert "gtm.email_send" not in charter.never_do
    assert "gtm.email_send" in charter.may_perform
    assert_action_allowed(
        action_name="gtm.email_send",
        side_effect_class=SideEffectClass.EXTERNAL_SEND,
        charter=charter,
    )


def test_dogfood_charter_still_blocks_social_publish() -> None:
    charter = dogfood_operating_charter()
    with pytest.raises(OperatingCharterViolation) as exc:
        assert_action_allowed(
            action_name="gtm.social_publish",
            side_effect_class=SideEffectClass.EXTERNAL_SEND,
            charter=charter,
        )
    assert exc.value.code == "CHARTER_NEVER_DO"


def test_load_dogfood_charter_from_profile_fact() -> None:
    charter = dogfood_operating_charter()
    loaded = load_operating_charter(
        approved_facts={"operating_charter": {"value": charter.to_fact_payload()}},
    )
    assert loaded.source == "profile"
    assert_action_allowed(
        action_name="gtm.email_send",
        side_effect_class=SideEffectClass.EXTERNAL_SEND,
        charter=loaded,
    )
