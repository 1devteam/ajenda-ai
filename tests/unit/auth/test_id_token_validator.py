"""Unit tests for OIDC id_token validation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.auth.id_token_validator import IdTokenValidator
from backend.auth.jwt_validator import JwtValidationError


def test_validate_rejects_nonce_mismatch() -> None:
    validator = IdTokenValidator(
        jwks_uri="https://idp.example.com/jwks",
        issuer="https://idp.example.com",
        audience="client-id",
    )
    with (
        patch.object(validator._cache, "get_keys", return_value=[{"kid": "k1", "kty": "RSA"}]),
        patch(
            "backend.auth.id_token_validator.jwt.decode",
            return_value={
                "sub": "user-1",
                "email": "owner@example.com",
                "email_verified": True,
                "nonce": "expected-nonce",
            },
        ),
        pytest.raises(JwtValidationError, match="nonce mismatch"),
    ):
        validator.validate("token", expected_nonce="different-nonce")


def test_validate_accepts_google_at_hash_when_access_token_provided() -> None:
    validator = IdTokenValidator(
        jwks_uri="https://idp.example.com/jwks",
        issuer="https://idp.example.com",
        audience="client-id",
    )
    with (
        patch.object(validator._cache, "get_keys", return_value=[{"kid": "k1", "kty": "RSA"}]),
        patch(
            "backend.auth.id_token_validator.jwt.decode",
            return_value={
                "sub": "user-1",
                "email": "owner@example.com",
                "email_verified": True,
                "at_hash": "hash-value",
            },
        ) as decode_mock,
    ):
        claims = validator.validate("token", access_token="provider-access-token")

    assert claims.sub == "user-1"
    assert decode_mock.call_args.kwargs["access_token"] == "provider-access-token"


def test_validate_requires_verified_email() -> None:
    validator = IdTokenValidator(
        jwks_uri="https://idp.example.com/jwks",
        issuer="https://idp.example.com",
        audience="client-id",
    )
    with (
        patch.object(validator._cache, "get_keys", return_value=[{"kid": "k1", "kty": "RSA"}]),
        patch(
            "backend.auth.id_token_validator.jwt.decode",
            return_value={
                "sub": "user-1",
                "email": "owner@example.com",
                "email_verified": False,
            },
        ),
        pytest.raises(JwtValidationError, match="not verified"),
    ):
        validator.validate("token")
