import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes.api_keys import router
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


def _token(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"


def test_api_key_routes_create() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.include_router(router)
    client = TestClient(app)
    token = _token({"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"]})
    response = client.post(
        "/api-keys",
        headers={"X-Tenant-Id": "tenant-a", "Authorization": f"Bearer {token}"},
        json={"scopes": ["execution:queue"]},
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"
