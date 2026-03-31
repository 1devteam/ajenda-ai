import base64
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware



def _token(payload: dict[str, object]) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
    return f"x.{encoded}.y"



def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(AuthContextMiddleware)

    @app.get("/protected")
    def protected(request: Request) -> dict[str, str]:
        principal = request.state.principal
        return {"subject_id": principal.subject_id}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app



def test_auth_context_injects_principal() -> None:
    client = TestClient(_app())
    token = _token({"sub": "user-1", "tenant_id": "tenant-a", "roles": ["tenant_admin"]})
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}", "X-Tenant-Id": "tenant-a"})
    assert response.status_code == 200
    assert response.json()["subject_id"] == "user-1"



def test_auth_context_denies_missing_auth_by_default() -> None:
    client = TestClient(_app())
    response = client.get("/protected", headers={"X-Tenant-Id": "tenant-a"})
    assert response.status_code == 401
    assert response.json()["detail"] == "missing authentication"



def test_auth_context_allows_public_health_without_auth() -> None:
    client = TestClient(_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
