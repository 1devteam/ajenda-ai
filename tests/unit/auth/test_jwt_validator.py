"""Unit tests for JwtValidator.

The real JwtValidator requires a live JWKS endpoint. These tests mock
JwksCache.get_keys() to test the validation logic without network calls.
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from backend.auth.jwt_validator import JwtValidationError, JwtValidator


def _make_validator() -> JwtValidator:
    """Build a JwtValidator with mocked JWKS fetch."""
    return JwtValidator(
        jwks_uri="https://example.com/.well-known/jwks.json",
        issuer="https://example.com",
        audience="ajenda-api",
    )


def test_jwt_validator_raises_on_malformed_token() -> None:
    """JwtValidator raises JwtValidationError on a token that cannot be decoded."""
    validator = _make_validator()
    # Patch get_keys to return a fake key so we get past the JWKS fetch
    with patch.object(validator._cache, "get_keys", return_value=[{"kty": "RSA", "kid": "test"}]):
        with pytest.raises(JwtValidationError):
            validator.validate_and_extract_claims("not.a.real.jwt")


def test_jwt_validator_raises_on_empty_token() -> None:
    """JwtValidator raises JwtValidationError on an empty token string."""
    validator = _make_validator()
    with patch.object(validator._cache, "get_keys", return_value=[{"kty": "RSA", "kid": "test"}]):
        with pytest.raises(JwtValidationError):
            validator.validate_and_extract_claims("")


def test_jwt_validator_raises_when_no_keys_available() -> None:
    """JwtValidator raises JwtValidationError when JWKS returns no keys."""
    validator = _make_validator()
    with patch.object(validator._cache, "get_keys", return_value=[]):
        with pytest.raises(JwtValidationError, match="no signing keys"):
            validator.validate_and_extract_claims("header.payload.sig")


def test_jwt_validator_raises_when_jwks_fetch_fails() -> None:
    """JwtValidator raises JwtValidationError when JWKS endpoint is unavailable."""
    validator = _make_validator()
    with patch.object(
        validator._cache, "get_keys",
        side_effect=RuntimeError("JWKS fetch failed and no cached keys available")
    ):
        with pytest.raises(JwtValidationError, match="temporarily unavailable"):
            validator.validate_and_extract_claims("header.payload.sig")


def test_jwt_validator_raises_on_expired_token() -> None:
    """JwtValidator raises JwtValidationError with 'expired' message for expired tokens."""
    from jose.exceptions import ExpiredSignatureError
    validator = _make_validator()
    with patch.object(validator._cache, "get_keys", return_value=[{"kty": "RSA", "kid": "test"}]):
        with patch("backend.auth.jwt_validator.jwt.decode", side_effect=ExpiredSignatureError("expired")):
            with pytest.raises(JwtValidationError, match="expired"):
                validator.validate_and_extract_claims("header.payload.sig")


def test_jwt_validator_returns_claims_on_valid_token() -> None:
    """JwtValidator returns the full claims dict on a valid token."""
    validator = _make_validator()
    mock_claims = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["tenant_admin"],
        "email": "a@example.com",
    }
    with patch.object(validator._cache, "get_keys", return_value=[{"kty": "RSA", "kid": "test"}]):
        with patch("backend.auth.jwt_validator.jwt.decode", return_value=mock_claims):
            claims = validator.validate_and_extract_claims("header.payload.sig")
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "tenant-a"
