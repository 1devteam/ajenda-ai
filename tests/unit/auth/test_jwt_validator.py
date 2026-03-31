import base64
import json

import pytest

from backend.auth.jwt_validator import JwtValidationError, JwtValidator


def _token(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"


def test_jwt_validator_parses_required_claims() -> None:
    token = _token({"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"]})
    claims = JwtValidator().parse_claims(token)
    assert claims.subject == "user-1"
    assert claims.tenant_id == "tenant-a"


def test_jwt_validator_rejects_missing_subject() -> None:
    token = _token({"tenant_id": "tenant-a", "roles": ["tenant_admin"]})
    with pytest.raises(JwtValidationError):
        JwtValidator().parse_claims(token)
