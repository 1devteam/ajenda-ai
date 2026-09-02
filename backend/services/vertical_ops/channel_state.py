"""Provider-neutral phone and social state-transition contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CallSessionState(StrEnum):
    RECEIVED = "received"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DISCLOSED = "disclosed"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    TRANSFERRING = "transferring"
    TRANSFERRED = "transferred"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FINALIZING = "finalizing"
    RECONCILED = "reconciled"


class SocialPublicationState(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    REJECTED = "rejected"
    AUTHORIZED = "authorized"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    FAILED_BEFORE_EFFECT = "failed_before_effect"
    PROVIDER_REJECTED = "provider_rejected"
    AMBIGUOUS = "ambiguous"
    PUBLISHED = "published"
    VERIFIED = "verified"
    REMOVED = "removed"
    NEEDS_HUMAN = "needs_human"


CALL_TRANSITIONS: dict[CallSessionState, frozenset[CallSessionState]] = {
    CallSessionState.RECEIVED: frozenset({CallSessionState.VERIFIED, CallSessionState.REJECTED}),
    CallSessionState.VERIFIED: frozenset({CallSessionState.DISCLOSED}),
    CallSessionState.REJECTED: frozenset(),
    CallSessionState.DISCLOSED: frozenset({CallSessionState.ACTIVE}),
    CallSessionState.ACTIVE: frozenset(
        {
            CallSessionState.ON_HOLD,
            CallSessionState.TRANSFERRING,
            CallSessionState.COMPLETED,
            CallSessionState.ABANDONED,
        }
    ),
    CallSessionState.ON_HOLD: frozenset({CallSessionState.ACTIVE, CallSessionState.ABANDONED}),
    CallSessionState.TRANSFERRING: frozenset(
        {CallSessionState.TRANSFERRED, CallSessionState.ACTIVE, CallSessionState.ABANDONED}
    ),
    CallSessionState.TRANSFERRED: frozenset({CallSessionState.FINALIZING}),
    CallSessionState.COMPLETED: frozenset({CallSessionState.FINALIZING}),
    CallSessionState.ABANDONED: frozenset({CallSessionState.FINALIZING}),
    CallSessionState.FINALIZING: frozenset({CallSessionState.RECONCILED}),
    CallSessionState.RECONCILED: frozenset(),
}

SOCIAL_TRANSITIONS: dict[SocialPublicationState, frozenset[SocialPublicationState]] = {
    SocialPublicationState.DRAFT: frozenset({SocialPublicationState.REVIEWED}),
    SocialPublicationState.REVIEWED: frozenset({SocialPublicationState.AUTHORIZED, SocialPublicationState.REJECTED}),
    SocialPublicationState.REJECTED: frozenset(),
    SocialPublicationState.AUTHORIZED: frozenset(
        {SocialPublicationState.UPLOADING, SocialPublicationState.FAILED_BEFORE_EFFECT}
    ),
    SocialPublicationState.UPLOADING: frozenset(
        {
            SocialPublicationState.PROCESSING,
            SocialPublicationState.FAILED_BEFORE_EFFECT,
            SocialPublicationState.AMBIGUOUS,
        }
    ),
    SocialPublicationState.PROCESSING: frozenset(
        {
            SocialPublicationState.PUBLISHED,
            SocialPublicationState.PROVIDER_REJECTED,
            SocialPublicationState.AMBIGUOUS,
        }
    ),
    SocialPublicationState.FAILED_BEFORE_EFFECT: frozenset(),
    SocialPublicationState.PROVIDER_REJECTED: frozenset(),
    SocialPublicationState.AMBIGUOUS: frozenset({SocialPublicationState.VERIFIED, SocialPublicationState.NEEDS_HUMAN}),
    SocialPublicationState.PUBLISHED: frozenset({SocialPublicationState.VERIFIED, SocialPublicationState.REMOVED}),
    SocialPublicationState.VERIFIED: frozenset({SocialPublicationState.REMOVED}),
    SocialPublicationState.REMOVED: frozenset(),
    SocialPublicationState.NEEDS_HUMAN: frozenset(),
}


class StateTransitionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str = Field(min_length=1, max_length=240)
    from_state: str = Field(min_length=1, max_length=80)
    to_state: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=500)
    source_artifact_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    grants_execution_authority: bool = False


def transition_call_session(
    *,
    session_id: str,
    current: CallSessionState,
    target: CallSessionState,
    reason: str,
    source_artifact_ids: tuple[str, ...],
) -> StateTransitionRecord:
    if target not in CALL_TRANSITIONS[current]:
        raise ValueError(f"invalid call session transition: {current.value}->{target.value}")
    return StateTransitionRecord(
        resource_id=session_id,
        from_state=current.value,
        to_state=target.value,
        reason=reason,
        source_artifact_ids=source_artifact_ids,
    )


def transition_social_publication(
    *,
    publication_id: str,
    current: SocialPublicationState,
    target: SocialPublicationState,
    reason: str,
    source_artifact_ids: tuple[str, ...],
) -> StateTransitionRecord:
    if target not in SOCIAL_TRANSITIONS[current]:
        raise ValueError(f"invalid social publication transition: {current.value}->{target.value}")
    return StateTransitionRecord(
        resource_id=publication_id,
        from_state=current.value,
        to_state=target.value,
        reason=reason,
        source_artifact_ids=source_artifact_ids,
    )
