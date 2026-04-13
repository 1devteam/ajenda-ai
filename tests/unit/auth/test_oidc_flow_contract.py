from types import SimpleNamespace

from backend.auth.jwt_validator import JwtClaims
from backend.auth.oidc import OidcAuthenticator


def test_oidc_authenticator_returns_claims(monkeypatch) -> None:
    authenticator = OidcAuthenticator(
        jwks_uri="https://example.com/.well-known/jwks.json",
        issuer="https://example.com/",
        audience="ajenda-api",
    )

    fake_claims = JwtClaims(
        sub="user-1",
        tenant_id="tenant-a",
        roles=["tenant_admin"],
        email=None,
        raw={
            "sub": "user-1",
            "tenant_id": "tenant-a",
            "roles": ["tenant_admin"],
        },
    )

    monkeypatch.setattr(
        authenticator,
        "_validator",
        SimpleNamespace(validate_and_extract_claims=lambda token: fake_claims),
    )

    result = authenticator.validate_bearer_token("dummy-token")
    assert result.claims.tenant_id == "tenant-a"
    assert result.principal.tenant_id == "tenant-a"
    assert result.principal.roles == ("tenant_admin",)
