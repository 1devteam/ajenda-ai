import base64
import json

from backend.auth.oidc import OidcAuthenticator


def _token(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"


def test_oidc_authenticator_returns_claims() -> None:
    token = _token({"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"]})
    result = OidcAuthenticator().validate_bearer_token(token)
    assert result.claims.tenant_id == "tenant-a"
