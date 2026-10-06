"""Unit tests for Ajenda customer session access tokens."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.auth.jwt_validator import JwtValidationError
from backend.auth.session_token import SessionTokenService


def test_issue_and_validate_access_token_round_trip() -> None:
    service = SessionTokenService(signing_secret="x" * 32, access_ttl_seconds=120)
    member_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    token, expires_at = service.issue_access_token(
        member_id=member_id,
        tenant_id=tenant_id,
        email="owner@example.com",
        roles=("tenant_admin",),
        jti="session-jti-1",
    )

    claims = service.validate_access_token(token)
    assert claims.jti == "session-jti-1"
    assert claims.member_id == str(member_id)
    assert claims.tenant_id == str(tenant_id)
    assert claims.email == "owner@example.com"
    assert claims.roles == ("tenant_admin",)
    assert abs((claims.expires_at - expires_at).total_seconds()) < 2


def test_validate_rejects_tampered_token() -> None:
    service = SessionTokenService(signing_secret="y" * 32, access_ttl_seconds=120)
    token, _ = service.issue_access_token(
        member_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="owner@example.com",
        roles=("tenant_admin",),
    )
    tampered = f"{token}tampered"
    with pytest.raises(JwtValidationError):
        service.validate_access_token(tampered)


def test_validate_rejects_expired_token() -> None:
    service = SessionTokenService(signing_secret="z" * 32, access_ttl_seconds=-10)
    token, _ = service.issue_access_token(
        member_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="owner@example.com",
        roles=("tenant_admin",),
    )
    assert datetime.now(tz=UTC) > datetime.now(tz=UTC) - timedelta(seconds=1)
    with pytest.raises(JwtValidationError):
        service.validate_access_token(token)

def test_session_validation_is_hs256_only(monkeypatch) -> None:
    service = SessionTokenService(signing_secret="s" * 32, access_ttl_seconds=120)
    observed: dict[str, object] = {}

    def fake_decode(token, key, *, algorithms, issuer, options):
        observed["algorithms"] = algorithms
        return {
            "typ": "customer_access",
            "jti": "session-jti",
            "sub": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()),
            "email": "owner@example.com",
            "roles": ["tenant_admin"],
            "exp": int(datetime.now(tz=UTC).timestamp()) + 60,
        }

    monkeypatch.setattr("backend.auth.session_token.jwt.decode", fake_decode)
    service.validate_access_token("header.payload.signature")

    assert observed["algorithms"] == ["HS256"]

