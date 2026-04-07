"""Unit tests for JwtValidator and JwtClaims.

Tests the real JWKS-backed validator by mocking the JwksCache.get_keys()
method to return a test RSA key, and tests JwtClaims.from_dict() directly.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.auth.jwt_validator import JwtClaims, JwtValidationError, JwtValidator


def test_jwt_claims_from_dict_parses_required_fields() -> None:
    """JwtClaims.from_dict builds a typed claims object from a verified dict."""
    raw = {"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"], "email": "u@example.com"}
    claims = JwtClaims.from_dict(raw)
    assert claims.sub == "user-1"
    assert claims.tenant_id == "tenant-a"
    assert claims.roles == ["tenant_admin"]
    assert claims.email == "u@example.com"
    assert claims.raw == raw


def test_jwt_claims_from_dict_rejects_missing_subject() -> None:
    """JwtClaims.from_dict raises JwtValidationError when sub is absent."""
    with pytest.raises(JwtValidationError, match="sub"):
        JwtClaims.from_dict({"tenant_id": "tenant-a"})


def test_jwt_claims_from_dict_rejects_missing_tenant_id() -> None:
    """JwtClaims.from_dict raises JwtValidationError when tenant_id is absent."""
    with pytest.raises(JwtValidationError, match="tenant_id"):
        JwtClaims.from_dict({"sub": "user-1"})


def test_jwt_claims_from_dict_accepts_tid_alias() -> None:
    """JwtClaims.from_dict accepts 'tid' as an alias for tenant_id (Azure AD compat)."""
    claims = JwtClaims.from_dict({"sub": "user-1", "tid": "tenant-a"})
    assert claims.tenant_id == "tenant-a"


def test_jwt_claims_roles_default_to_empty_list() -> None:
    """JwtClaims.from_dict defaults roles to empty list when absent."""
    claims = JwtClaims.from_dict({"sub": "user-1", "tenant_id": "tenant-a"})
    assert claims.roles == []


def test_jwt_validator_calls_jwks_cache_and_decodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """JwtValidator.validate_and_extract_claims() calls JwksCache and returns claims dict."""
    from backend.auth.jwt_validator import JwksCache

    fake_claims = {"sub": "user-1", "tenant_id": "tenant-a", "roles": []}
    with patch.object(JwksCache, "get_keys", return_value=[{"kty": "RSA"}]):
        with patch("backend.auth.jwt_validator.jwt.decode", return_value=fake_claims) as mock_decode:
            validator = JwtValidator(
                jwks_uri="https://example.com/.well-known/jwks.json",
                issuer="https://example.com/",
                audience="ajenda-api",
            )
            result = validator.validate_and_extract_claims("header.payload.sig")
            assert result == fake_claims
            mock_decode.assert_called_once()


def test_jwt_validator_raises_on_empty_keyset() -> None:
    """JwtValidator raises JwtValidationError when JWKS returns no keys."""
    from backend.auth.jwt_validator import JwksCache

    with patch.object(JwksCache, "get_keys", return_value=[]):
        validator = JwtValidator(
            jwks_uri="https://example.com/.well-known/jwks.json",
            issuer="https://example.com/",
            audience="ajenda-api",
        )
        with pytest.raises(JwtValidationError, match="no signing keys"):
            validator.validate_and_extract_claims("header.payload.sig")


def test_jwt_validator_raises_on_cache_failure() -> None:
    """JwtValidator raises JwtValidationError when JWKS cache fails with no prior keys."""
    from backend.auth.jwt_validator import JwksCache

    with patch.object(JwksCache, "get_keys", side_effect=RuntimeError("fetch failed")):
        validator = JwtValidator(
            jwks_uri="https://example.com/.well-known/jwks.json",
            issuer="https://example.com/",
            audience="ajenda-api",
        )
        with pytest.raises(JwtValidationError, match="temporarily unavailable"):
            validator.validate_and_extract_claims("header.payload.sig")
