from __future__ import annotations

from typing import Any

import pytest

from backend.auth.oidc import OidcValidationResult
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.services.identity_service import IdentityService


class _Oidc:
    def validate_bearer_token(self, token: str) -> OidcValidationResult:
        assert token == "token-1"
        principal = UserPrincipal(
            subject_id="user-1",
            tenant_id="tenant-a",
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
            email="a@example.com",
        )
        return OidcValidationResult(
            claims={
                "sub": "user-1",
                "tenant_id": "tenant-a",
                "roles": ["tenant_admin"],
                "email": "a@example.com",
            },
            principal=principal,
            provider="test",
        )


def test_identity_service_requires_injected_oidc() -> None:
    with pytest.raises(RuntimeError, match="requires an OidcAuthenticator"):
        IdentityService().authenticate_user_bearer("token-1")


def test_identity_service_builds_user_principal_from_oidc_result() -> None:
    service = IdentityService(oidc=_Oidc())  # type: ignore[arg-type]

    principal = service.authenticate_user_bearer("token-1")

    assert principal.subject_id == "user-1"
    assert principal.tenant_id == "tenant-a"
    assert principal.email == "a@example.com"
    assert "tenant_admin" in principal.roles
    assert principal.permissions


def test_identity_service_does_not_read_claims_as_attributes() -> None:
    class OidcWithDictClaims(_Oidc):
        def validate_bearer_token(self, token: str) -> OidcValidationResult:
            result = super().validate_bearer_token(token)
            claims: dict[str, Any] = {"roles": ["wrong_shape_only"]}
            return OidcValidationResult(
                claims=claims,
                principal=result.principal,
                provider=result.provider,
            )

    principal = IdentityService(oidc=OidcWithDictClaims()).authenticate_user_bearer(  # type: ignore[arg-type]
        "token-1"
    )

    assert principal.subject_id == "user-1"
    assert principal.tenant_id == "tenant-a"
