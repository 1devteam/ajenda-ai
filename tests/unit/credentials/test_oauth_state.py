from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.services.credentials.oauth_state import OAuthStateError, sign_oauth_state


def test_signing_key_allows_fallback_in_test_env() -> None:
    settings = Settings.model_construct(env="test", session_signing_secret="", runtime_secret_encryption_key="")
    state = sign_oauth_state(
        {
            "tenant_id": "tenant-1",
            "credential_id": "cred-1",
            "actor_id": "actor-1",
            "nonce": "nonce",
            "issued_at": 1_700_000_000,
            "provider": "gmail",
        },
        settings=settings,
    )
    assert "." in state


def test_signing_key_rejects_fallback_in_staging_env() -> None:
    settings = Settings.model_construct(env="staging", session_signing_secret="", runtime_secret_encryption_key="")
    with pytest.raises(OAuthStateError, match="signing secret is not configured"):
        sign_oauth_state(
            {
                "tenant_id": "tenant-1",
                "credential_id": "cred-1",
                "actor_id": "actor-1",
                "nonce": "nonce",
                "issued_at": 1_700_000_000,
                "provider": "gmail",
            },
            settings=settings,
        )