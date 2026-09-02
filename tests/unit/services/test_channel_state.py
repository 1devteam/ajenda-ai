from __future__ import annotations

import pytest

from backend.services.vertical_ops.channel_state import (
    CallSessionState,
    SocialPublicationState,
    transition_call_session,
    transition_social_publication,
)


def test_call_requires_verification_and_disclosure_before_active() -> None:
    with pytest.raises(ValueError, match="invalid call session transition"):
        transition_call_session(
            session_id="call-1",
            current=CallSessionState.RECEIVED,
            target=CallSessionState.ACTIVE,
            reason="unsafe skip",
            source_artifact_ids=("event-1",),
        )
    verified = transition_call_session(
        session_id="call-1",
        current=CallSessionState.RECEIVED,
        target=CallSessionState.VERIFIED,
        reason="signed callback and tenant mapping verified",
        source_artifact_ids=("event-1",),
    )
    assert verified.grants_execution_authority is False


def test_failed_transfer_returns_to_controlled_active_session() -> None:
    transition = transition_call_session(
        session_id="call-1",
        current=CallSessionState.TRANSFERRING,
        target=CallSessionState.ACTIVE,
        reason="transfer failed safely",
        source_artifact_ids=("transfer-result-1",),
    )
    assert transition.to_state == "active"


def test_social_publish_cannot_skip_review_and_authorization() -> None:
    with pytest.raises(ValueError, match="invalid social publication transition"):
        transition_social_publication(
            publication_id="post-1",
            current=SocialPublicationState.DRAFT,
            target=SocialPublicationState.UPLOADING,
            reason="unsafe skip",
            source_artifact_ids=("draft-1",),
        )


def test_ambiguous_publication_cannot_be_marked_failed_for_retry() -> None:
    with pytest.raises(ValueError, match="invalid social publication transition"):
        transition_social_publication(
            publication_id="post-1",
            current=SocialPublicationState.AMBIGUOUS,
            target=SocialPublicationState.FAILED_BEFORE_EFFECT,
            reason="blind retry attempt",
            source_artifact_ids=("provider-attempt-1",),
        )
    transition = transition_social_publication(
        publication_id="post-1",
        current=SocialPublicationState.AMBIGUOUS,
        target=SocialPublicationState.NEEDS_HUMAN,
        reason="provider state cannot be resolved",
        source_artifact_ids=("provider-attempt-1",),
    )
    assert transition.to_state == "needs_human"
