"""Unit tests for IdentityService.

These tests inject a mock OidcAuthenticator since real JWKS validation
requires a live identity provider. The contract being tested here is
that IdentityService correctly maps OIDC claims to a UserPrincipal.
"""
from __future__ import annotations
from unittest.mock import MagicMock
from backend.auth.oidc import OidcValidationResult
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.services.identity_service import IdentityService


def _make_oidc_result(claims: dict) -> OidcValidationResult:
    """Build a mock OidcValidationResult from raw claims."""
    principal = UserPrincipal(
        subject_id=claims["sub"],
        tenant_id=claims["tenant_id"],
        principal_type=PrincipalType.USER,
        roles=tuple(claims.get("roles", [])),
        email=claims.get("email"),
    )
    return OidcValidationResult(claims=claims, principal=principal, provider="mock")


def test_identity_service_builds_user_principal() -> None:
    """IdentityService maps OIDC claims to a correctly structured UserPrincipal."""
    mock_oidc = MagicMock()
    mock_oidc.validate_bearer_token.return_value = _make_oidc_result({
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["tenant_admin"],
        "email": "a@example.com",
    })

    service = IdentityService(oidc=mock_oidc)
    principal = service.authenticate_user_bearer("any.token.here")

    assert principal.tenant_id == "tenant-a"
    assert principal.email == "a@example.com"
    assert principal.subject_id == "user-1"
    assert "tenant_admin" in principal.roles


def test_identity_service_propagates_jwt_validation_error() -> None:
    """IdentityService propagates JwtValidationError from the OIDC layer."""
    from backend.auth.jwt_validator import JwtValidationError

    mock_oidc = MagicMock()
    mock_oidc.validate_bearer_token.side_effect = JwtValidationError("token has expired")

    service = IdentityService(oidc=mock_oidc)
    try:
        service.authenticate_user_bearer("expired.token.here")
        assert False, "Should have raised JwtValidationError"
    except JwtValidationError as exc:
        assert "expired" in str(exc)


def test_identity_service_raises_without_oidc() -> None:
    """IdentityService raises RuntimeError if no OidcAuthenticator is injected."""
    service = IdentityService()
    try:
        service.authenticate_user_bearer("any.token.here")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as exc:
        assert "OidcAuthenticator" in str(exc)
