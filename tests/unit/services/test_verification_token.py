"""Unit tests for verification token issuance."""

from __future__ import annotations

from backend.services.verification_token import VerificationTokenIssuer


def test_verification_token_issue_and_verify() -> None:
    issuer = VerificationTokenIssuer(ttl_hours=24)
    issued = issuer.issue()
    assert len(issued.plaintext) >= 32
    assert issuer.verify(plaintext=issued.plaintext, token_hash=issued.token_hash)
    assert not issuer.verify(plaintext="wrong-token", token_hash=issued.token_hash)
