from __future__ import annotations

import pytest

from backend.services.autonomy.disclaimer_catalog import (
    AutonomyPolicyError,
    action_tier,
    disclaimer_for_action,
    load_disclaimer_catalog,
    parse_autonomy_acknowledgment,
    validate_autonomy_acknowledgment,
)


def test_catalog_loads_and_hashes_are_stable() -> None:
    entries = load_disclaimer_catalog()
    assert len(entries) >= 4
    send_entry = disclaimer_for_action("gtm.email_send")
    assert send_entry is not None
    assert send_entry.disclaimer_id == "autonomy.external_send.v1"
    assert send_entry.text_hash.startswith("sha256:")


def test_validate_acknowledgment_requires_matching_action_and_hash() -> None:
    entry = disclaimer_for_action("gtm.crm_upsert")
    assert entry is not None
    ack = parse_autonomy_acknowledgment(
        {
            "schema_version": 1,
            "disclaimer_id": entry.disclaimer_id,
            "disclaimer_text_hash": entry.text_hash,
            "accepted_at": "2026-06-25T12:00:00Z",
            "principal_id": "human:owner@example.com",
            "action": "gtm.crm_upsert",
            "side_effect_class": "external_write",
        }
    )
    validated = validate_autonomy_acknowledgment(acknowledgment=ack, action_name="gtm.crm_upsert")
    assert validated.tier == 3


def test_validate_rejects_hash_mismatch() -> None:
    entry = disclaimer_for_action("gtm.email_send")
    assert entry is not None
    ack = parse_autonomy_acknowledgment(
        {
            "schema_version": 1,
            "disclaimer_id": entry.disclaimer_id,
            "disclaimer_text_hash": "sha256:deadbeef",
            "accepted_at": "2026-06-25T12:00:00Z",
            "principal_id": "human:owner@example.com",
            "action": "gtm.email_send",
        }
    )
    with pytest.raises(AutonomyPolicyError, match="hash"):
        validate_autonomy_acknowledgment(acknowledgment=ack, action_name="gtm.email_send")


def test_action_tier_mapping() -> None:
    assert action_tier("record.search") == 0
    assert action_tier("gtm.email_draft") == 1
    assert action_tier("gtm.email_check") == 2
    assert action_tier("gtm.email_send") == 3
