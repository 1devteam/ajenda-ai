"""Unit tests for verification code issuance."""

from __future__ import annotations

from backend.services.verification_token import VerificationTokenIssuer


def test_verification_code_issue_and_verify() -> None:
    issuer = VerificationTokenIssuer(ttl_hours=24)
    issued = issuer.issue()
    assert len(issued.plaintext) == 6
    assert issued.plaintext.isdigit()
    assert issuer.verify(plaintext=issued.plaintext, token_hash=issued.token_hash)
    assert not issuer.verify(
        plaintext="000000" if issued.plaintext != "000000" else "999999", token_hash=issued.token_hash
    )
