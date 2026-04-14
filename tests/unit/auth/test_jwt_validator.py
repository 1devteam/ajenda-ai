"""Unit tests for JwtValidator and JwtClaims."""

from __future__ import annotations

import pytest

from backend.auth.jwt_validator import JwtClaims, JwtValidationError, JwtValidator


def test_jwtclaims_from_dict_builds_typed_claims() -> None:
    raw = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["tenant_admin"],
        "email": "user@example.com",
    }
    claims = JwtClaims.from_dict(raw)
    assert claims.sub == "user-1"
    assert claims.tenant_id == "tenant-a"
    assert claims.roles == ["tenant_admin"]
    assert claims.email == "user@example.com"
    assert claims.raw == raw


def test_jwtclaims_from_dict_rejects_missing_sub() -> None:
    with pytest.raises(JwtValidationError, match="sub"):
        JwtClaims.from_dict({"tenant_id": "tenant-a"})


def test_jwtclaims_from_dict_rejects_missing_tenant_id() -> None:
    with pytest.raises(JwtValidationError, match="tenant_id"):
        JwtClaims.from_dict({"sub": "user-1"})


def test_jwtclaims_from_dict_accepts_tid_alias() -> None:
    claims = JwtClaims.from_dict({"sub": "user-1", "tid": "tenant-a"})
    assert claims.tenant_id == "tenant-a"


def test_jwtclaims_from_dict_normalizes_string_roles() -> None:
    claims = JwtClaims.from_dict({"sub": "user-1", "tenant_id": "tenant-a", "roles": "tenant_admin"})
    assert claims.roles == ["tenant_admin"]


def test_jwtclaims_from_dict_defaults_roles_to_empty_list() -> None:
    claims = JwtClaims.from_dict({"sub": "user-1", "tenant_id": "tenant-a"})
    assert claims.roles == []


def test_jwtvalidator_returns_typed_claims(monkeypatch) -> None:
    validator = JwtValidator(
        jwks_uri="https://example.com/.well-known/jwks.json",
        issuer="https://example.com/",
        audience="ajenda-api",
    )

    monkeypatch.setattr(validator._cache, "get_keys", lambda: [{"kid": "k1"}])
    monkeypatch.setattr(
        "backend.auth.jwt_validator.jwt.decode",
        lambda token, key, algorithms, audience, issuer, options: {
            "sub": "user-1",
            "tenant_id": "tenant-a",
            "roles": ["tenant_admin"],
        },
    )

    result = validator.validate_and_extract_claims("header.payload.sig")
    assert isinstance(result, JwtClaims)
    assert result.sub == "user-1"
    assert result.tenant_id == "tenant-a"
    assert result.roles == ["tenant_admin"]


def test_jwtvalidator_fails_closed_when_no_keys_available(monkeypatch) -> None:
    validator = JwtValidator(
        jwks_uri="https://example.com/.well-known/jwks.json",
        issuer="https://example.com/",
        audience="ajenda-api",
    )

    monkeypatch.setattr(validator._cache, "get_keys", lambda: [])

    with pytest.raises(JwtValidationError, match="no signing keys available"):
        validator.validate_and_extract_claims("header.payload.sig")


def test_jwtvalidator_fails_closed_when_jwks_unavailable(monkeypatch) -> None:
    validator = JwtValidator(
        jwks_uri="https://example.com/.well-known/jwks.json",
        issuer="https://example.com/",
        audience="ajenda-api",
    )

    def blow_up():
        raise RuntimeError("jwks down")

    monkeypatch.setattr(validator._cache, "get_keys", blow_up)

    with pytest.raises(JwtValidationError, match="temporarily unavailable"):
        validator.validate_and_extract_claims("header.payload.sig")
