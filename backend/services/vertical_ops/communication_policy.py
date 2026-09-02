"""Owner-configured communication eligibility contracts.

No jurisdiction rules are embedded here. The evaluator consumes an explicitly
versioned owner/legal policy and fails closed when required facts are absent.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommunicationChannel(StrEnum):
    PHONE_OUTBOUND = "phone_outbound"
    PHONE_RECORDING = "phone_recording"
    EMAIL = "email"
    SOCIAL_MESSAGE = "social_message"
    SOCIAL_PUBLISH = "social_publish"


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    REVOKED = "revoked"
    UNKNOWN = "unknown"
    NOT_REQUIRED_BY_APPROVED_POLICY = "not_required_by_approved_policy"


class CommunicationEligibility(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    INDETERMINATE = "indeterminate"


class ConsentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1, max_length=160)
    channel: CommunicationChannel
    status: ConsentStatus
    source_artifact_id: str = Field(min_length=1, max_length=240)
    observed_at_iso: str = Field(min_length=1, max_length=80)


class SuppressionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1, max_length=160)
    channel: CommunicationChannel
    suppressed: bool
    reason: str = Field(min_length=1, max_length=500)
    source_artifact_id: str = Field(min_length=1, max_length=240)


class JurisdictionChannelRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    jurisdiction: str = Field(min_length=1, max_length=120)
    channel: CommunicationChannel
    enabled: bool = False
    consent_required: bool = True
    allowed_local_hour_start: int | None = Field(default=None, ge=0, le=23)
    allowed_local_hour_end: int | None = Field(default=None, ge=1, le=24)

    @model_validator(mode="after")
    def validate_hours(self) -> JurisdictionChannelRule:
        if (self.allowed_local_hour_start is None) != (self.allowed_local_hour_end is None):
            raise ValueError("communication hour window requires both start and end")
        if self.allowed_local_hour_start is not None and self.allowed_local_hour_end is not None:
            if self.allowed_local_hour_start >= self.allowed_local_hour_end:
                raise ValueError("communication hour window must be increasing within one local day")
        return self


class CommunicationPolicySet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1)
    policy_id: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$", max_length=40)
    owner_approved: bool = False
    rules: tuple[JurisdictionChannelRule, ...]

    @model_validator(mode="after")
    def validate_unique_rules(self) -> CommunicationPolicySet:
        keys = {(rule.jurisdiction.casefold(), rule.channel) for rule in self.rules}
        if len(keys) != len(self.rules):
            raise ValueError("communication policy rules must be unique by jurisdiction and channel")
        return self


class CommunicationEligibilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str
    channel: CommunicationChannel
    eligibility: CommunicationEligibility
    policy_id: str
    policy_version: str
    reasons: tuple[str, ...] = Field(min_length=1)
    source_artifact_ids: tuple[str, ...]
    grants_execution_authority: bool = False

    @model_validator(mode="after")
    def reject_authority(self) -> CommunicationEligibilityDecision:
        if self.grants_execution_authority:
            raise ValueError("communication eligibility cannot grant execution authority")
        return self


def evaluate_communication_eligibility(
    *,
    subject_id: str,
    channel: CommunicationChannel,
    jurisdiction: str | None,
    timezone_name: str | None,
    evaluated_at: datetime,
    policy: CommunicationPolicySet,
    consent: ConsentObservation | None,
    suppression: SuppressionObservation | None,
) -> CommunicationEligibilityDecision:
    source_ids = tuple(sorted({item.source_artifact_id for item in (consent, suppression) if item is not None}))
    if not policy.owner_approved:
        return _decision(
            subject_id,
            channel,
            policy,
            CommunicationEligibility.INDETERMINATE,
            ("Policy is not owner-approved.",),
            source_ids,
        )
    if not jurisdiction:
        return _decision(
            subject_id,
            channel,
            policy,
            CommunicationEligibility.INDETERMINATE,
            ("Jurisdiction is unknown.",),
            source_ids,
        )
    rule = next(
        (
            item
            for item in policy.rules
            if item.jurisdiction.casefold() == jurisdiction.casefold() and item.channel == channel
        ),
        None,
    )
    if rule is None:
        return _decision(
            subject_id,
            channel,
            policy,
            CommunicationEligibility.INDETERMINATE,
            ("No approved jurisdiction/channel rule exists.",),
            source_ids,
        )
    if not rule.enabled:
        return _decision(
            subject_id,
            channel,
            policy,
            CommunicationEligibility.BLOCKED,
            ("The channel is disabled by policy.",),
            source_ids,
        )
    if (
        suppression
        and suppression.subject_id == subject_id
        and suppression.channel == channel
        and suppression.suppressed
    ):
        return _decision(
            subject_id,
            channel,
            policy,
            CommunicationEligibility.BLOCKED,
            (f"Subject is suppressed: {suppression.reason}",),
            source_ids,
        )
    if rule.consent_required:
        if consent is None or consent.subject_id != subject_id or consent.channel != channel:
            return _decision(
                subject_id,
                channel,
                policy,
                CommunicationEligibility.INDETERMINATE,
                ("Required consent is absent.",),
                source_ids,
            )
        if consent.status != ConsentStatus.GRANTED:
            return _decision(
                subject_id,
                channel,
                policy,
                CommunicationEligibility.BLOCKED,
                (f"Consent status is {consent.status.value}.",),
                source_ids,
            )
    if rule.allowed_local_hour_start is not None:
        if not timezone_name:
            return _decision(
                subject_id,
                channel,
                policy,
                CommunicationEligibility.INDETERMINATE,
                ("Local timezone is unknown.",),
                source_ids,
            )
        try:
            local_hour = evaluated_at.astimezone(ZoneInfo(timezone_name)).hour
        except ZoneInfoNotFoundError:
            return _decision(
                subject_id,
                channel,
                policy,
                CommunicationEligibility.INDETERMINATE,
                ("Local timezone is invalid.",),
                source_ids,
            )
        assert rule.allowed_local_hour_end is not None
        if not rule.allowed_local_hour_start <= local_hour < rule.allowed_local_hour_end:
            return _decision(
                subject_id,
                channel,
                policy,
                CommunicationEligibility.BLOCKED,
                ("Current local time is outside the approved communication window.",),
                source_ids,
            )
    return _decision(
        subject_id,
        channel,
        policy,
        CommunicationEligibility.ALLOWED,
        ("All configured policy prerequisites are satisfied.",),
        source_ids,
    )


def _decision(
    subject_id: str,
    channel: CommunicationChannel,
    policy: CommunicationPolicySet,
    eligibility: CommunicationEligibility,
    reasons: tuple[str, ...],
    source_artifact_ids: tuple[str, ...],
) -> CommunicationEligibilityDecision:
    return CommunicationEligibilityDecision(
        subject_id=subject_id,
        channel=channel,
        eligibility=eligibility,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        reasons=reasons,
        source_artifact_ids=source_artifact_ids,
    )
