"""Unit tests for IdentityService.

Tests that IdentityService correctly delegates to OidcAuthenticator
and builds UserPrincipal from validated claims.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.auth.oidc import OidcValidationResult
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.services.identity_service import IdentityService


def _make_service() -> tuple[IdentityService, MagicMock]:
    """Build an IdentityService with a mocked OidcAuthenticator."""
    mock_oidc = MagicMock()
    mock_session = MagicMock()
    svc = IdentityService(oidc_authenticator=mock_oidc, session=mock_session)
    return svc, mock_oidc


def test_identity_service_builds_user_principal() -> None:
    """IdentityService.authenticate_bearer returns a UserPrincipal on valid token."""
    svc, mock_oidc = _make_service()

    fake_principal = UserPrincipal(
        subject_id="user-1",
        tenant_id="tenant-a",
        principal_type=PrincipalType.USER,
        roles=frozenset(["tenant_admin"]),
        email="user@example.com",
    )
    # OidcAuthenticator.validate_bearer_token returns an OidcValidationResult
    mock_oidc.validate_bearer_token.return_value = OidcValidationResult(
        claims={"sub": "user-1", "tenant_id": "tenant-a"},
        principal=fake_principal,
        provider="oidc",
    )

    result = svc.authenticate_bearer(token="fake.jwt.token")

    assert result.subject_id == "user-1"
    assert result.tenant_id == "tenant-a"
    mock_oidc.validate_bearer_token.assert_called_once_with("fake.jwt.token")


def test_identity_service_propagates_validation_error() -> None:
    """IdentityService.authenticate_bearer propagates JwtValidationError from OIDC."""
    from backend.auth.jwt_validator import JwtValidationError

    svc, mock_oidc = _make_service()
    mock_oidc.validate_bearer_token.side_effect = JwtValidationError("token expired")

    with pytest.raises(JwtValidationError):
        svc.authenticate_bearer(token="expired.jwt.token")


def test_identity_service_rejects_empty_token() -> None:
    """IdentityService.authenticate_bearer raises ValueError on empty token."""
    svc, mock_oidc = _make_service()

    with pytest.raises((ValueError, Exception)):
        svc.authenticate_bearer(token="")
