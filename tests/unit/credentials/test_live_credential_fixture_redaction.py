from __future__ import annotations

from tests.integration.credentials.credential_e2e_support import _RedactedLiveSecret


def test_live_credential_fixture_representation_is_redacted() -> None:
    secret = _RedactedLiveSecret("credential-value-must-not-appear")

    assert str(secret) == "credential-value-must-not-appear"
    assert repr(secret) == "<redacted-live-credential>"
    assert "credential-value-must-not-appear" not in repr(secret)
