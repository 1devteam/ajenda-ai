import base64
import json

from fastapi.testclient import TestClient
from fastapi import FastAPI

from backend.api.routes.auth import router


def _token(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"


def test_auth_route_returns_principal() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = _token({"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"]})
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"
