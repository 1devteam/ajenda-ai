from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware



def test_fail_closed_auth_blocks_unprotected_route_without_principal() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(AuthContextMiddleware)

    @app.get("/runtime/private")
    def private() -> dict[str, str]:
        return {"status": "should-not-pass"}

    client = TestClient(app)
    response = client.get("/runtime/private", headers={"X-Tenant-Id": "tenant-a"})
    assert response.status_code == 401
    assert response.json()["detail"] == "missing authentication"
