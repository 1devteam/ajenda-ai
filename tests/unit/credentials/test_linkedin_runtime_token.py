from __future__ import annotations

import json

from backend.services.credentials.linkedin_runtime_token import is_linkedin_oauth_secret


def test_is_linkedin_oauth_secret_accepts_provider_kind() -> None:
    payload = json.dumps({"provider_kind": "linkedin", "access_token": "a"})
    assert is_linkedin_oauth_secret(payload) is True


def test_is_linkedin_oauth_secret_accepts_explicit_legacy_shape() -> None:
    payload = json.dumps(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": "2026-06-25T12:00:00+00:00",
            "scopes": ["openid", "profile", "email"],
        }
    )
    assert is_linkedin_oauth_secret(payload) is True


def test_is_linkedin_oauth_secret_rejects_generic_access_refresh_without_shape() -> None:
    payload = json.dumps({"access_token": "access", "refresh_token": "refresh"})
    assert is_linkedin_oauth_secret(payload) is False


def test_is_linkedin_oauth_secret_rejects_salesforce_shape() -> None:
    payload = json.dumps(
        {
            "provider_kind": "salesforce",
            "access_token": "access",
            "refresh_token": "refresh",
            "instance_url": "https://example.my.salesforce.com",
        }
    )
    assert is_linkedin_oauth_secret(payload) is False
