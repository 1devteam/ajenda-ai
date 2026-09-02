from __future__ import annotations

from datetime import UTC, datetime

from backend.services.vertical_ops.communication_policy import (
    CommunicationChannel,
    CommunicationEligibility,
    CommunicationPolicySet,
    ConsentObservation,
    ConsentStatus,
    JurisdictionChannelRule,
    SuppressionObservation,
    evaluate_communication_eligibility,
)


def _policy(*, approved: bool = True, enabled: bool = True) -> CommunicationPolicySet:
    return CommunicationPolicySet(
        policy_id="owner-phone-policy",
        policy_version="1.0.0",
        owner_approved=approved,
        rules=(
            JurisdictionChannelRule(
                jurisdiction="US-TEST",
                channel=CommunicationChannel.PHONE_OUTBOUND,
                enabled=enabled,
                consent_required=True,
                allowed_local_hour_start=9,
                allowed_local_hour_end=17,
            ),
        ),
    )


def _consent(status: ConsentStatus = ConsentStatus.GRANTED) -> ConsentObservation:
    return ConsentObservation(
        subject_id="person-1",
        channel=CommunicationChannel.PHONE_OUTBOUND,
        status=status,
        source_artifact_id="consent-1",
        observed_at_iso="2026-09-02T00:00:00Z",
    )


def _evaluate(**updates: object):
    arguments = {
        "subject_id": "person-1",
        "channel": CommunicationChannel.PHONE_OUTBOUND,
        "jurisdiction": "US-TEST",
        "timezone_name": "UTC",
        "evaluated_at": datetime(2026, 9, 2, 12, tzinfo=UTC),
        "policy": _policy(),
        "consent": _consent(),
        "suppression": None,
    }
    arguments.update(updates)
    return evaluate_communication_eligibility(**arguments)  # type: ignore[arg-type]


def test_owner_unapproved_policy_is_indeterminate_and_grants_no_authority() -> None:
    decision = _evaluate(policy=_policy(approved=False))
    assert decision.eligibility == CommunicationEligibility.INDETERMINATE
    assert decision.grants_execution_authority is False


def test_missing_jurisdiction_or_consent_fails_closed() -> None:
    assert _evaluate(jurisdiction=None).eligibility == CommunicationEligibility.INDETERMINATE
    assert _evaluate(consent=None).eligibility == CommunicationEligibility.INDETERMINATE


def test_denied_or_revoked_consent_blocks() -> None:
    assert _evaluate(consent=_consent(ConsentStatus.DENIED)).eligibility == CommunicationEligibility.BLOCKED
    assert _evaluate(consent=_consent(ConsentStatus.REVOKED)).eligibility == CommunicationEligibility.BLOCKED


def test_suppression_overrides_granted_consent() -> None:
    suppression = SuppressionObservation(
        subject_id="person-1",
        channel=CommunicationChannel.PHONE_OUTBOUND,
        suppressed=True,
        reason="do not call",
        source_artifact_id="suppression-1",
    )
    decision = _evaluate(suppression=suppression)
    assert decision.eligibility == CommunicationEligibility.BLOCKED
    assert set(decision.source_artifact_ids) == {"consent-1", "suppression-1"}


def test_local_time_window_blocks_outside_hours() -> None:
    decision = _evaluate(evaluated_at=datetime(2026, 9, 2, 22, tzinfo=UTC))
    assert decision.eligibility == CommunicationEligibility.BLOCKED


def test_all_owner_configured_prerequisites_allow_but_do_not_authorize() -> None:
    decision = _evaluate()
    assert decision.eligibility == CommunicationEligibility.ALLOWED
    assert decision.grants_execution_authority is False
