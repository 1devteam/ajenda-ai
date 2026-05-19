from unittest.mock import patch

from backend.auth.oidc import OidcAuthenticator


def test_oidc_authenticator_returns_principal_from_claims() -> None:
    claims = {
        "sub": "user-1",
        "tenant_id": "tenant-a",
        "roles": ["tenant_admin"],
    }

    with patch("backend.auth.oidc.JwtValidator") as validator_cls:
        validator_cls.return_value.validate_and_extract_claims.return_value = claims
        result = OidcAuthenticator(
            jwks_uri="https://issuer.example.test/jwks.json",
            issuer="https://issuer.example.test/",
            audience="ajenda-api",
        ).validate_bearer_token("opaque-test-token")

    assert result.claims == claims
    assert result.principal.tenant_id == "tenant-a"
    assert result.principal.subject_id == "user-1"
    assert result.principal.roles == ("tenant_admin",)
