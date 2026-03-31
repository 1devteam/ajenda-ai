import base64
import json

from backend.services.identity_service import IdentityService


def _token(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"


def test_identity_service_builds_user_principal() -> None:
    token = _token({"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"], "email": "a@example.com"})
    principal = IdentityService().authenticate_user_bearer(token)
    assert principal.tenant_id == "tenant-a"
    assert principal.email == "a@example.com"
