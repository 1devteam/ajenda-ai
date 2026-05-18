from __future__ import annotations

from unittest.mock import patch

import pytest
from jose.exceptions import ExpiredSignatureError

from backend.auth.jwt_validator import JwtValidationError, JwtValidator


def _validator() -> JwtValidator:
    return JwtValidator(
        jwks_uri="https://issuer.example/.well-known/jwks.json",
        issuer="https://issuer.example",
        audience="ajenda-api",
    )


def test_jwt_validator_rejects_empty_key_set() -> None:
    validator = _validator()

    with patch.object(validator._cache, "get_keys", return_value=[]):
        with pytest.raises(JwtValidationError, match="no signing keys"):
            validator.validate_and_extract_claims("header.payload.signature")


def test_jwt_validator_rejects_jwks_fetch_failure() -> None:
    validator = _validator()

    with patch.object(
        validator._cache,
        "get_keys",
        side_effect=RuntimeError("jwks unavailable"),
    ):
        with pytest.raises(JwtValidationError, match="temporarily unavailable"):
            validator.validate_and_extract_claims("header.payload.signature")


def test_jwt_validator_rejects_expired_token() -> None:
    validator = _validator()

    with patch.object(validator._cache, "get_keys", return_value=[{"kid": "k1"}]):
        with patch(
            "backend.auth.jwt_validator.jwt.decode",
            side_effect=ExpiredSignatureError("expired"),
        ):
            with pytest.raises(JwtValidationError, match="expired"):
                validator.validate_and_extract_claims("header.payload.signature")


def test_jwt_validator_returns_verified_claims() -> None:
    validator = _validator()
    expected_claims = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["tenant_admin"],
        "email": "a@example.com",
    }

    with patch.object(validator._cache, "get_keys", return_value=[{"kid": "k1"}]):
        with patch("backend.auth.jwt_validator.jwt.decode", return_value=expected_claims):
            claims = validator.validate_and_extract_claims("header.payload.signature")

    assert claims == expected_claims
