from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.routes.auth import router
from backend.auth.principal import PrincipalType, UserPrincipal


class PrincipalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = UserPrincipal(
            subject_id="user-1",
            tenant_id="tenant-a",
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)


def test_auth_route_returns_principal() -> None:
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(PrincipalMiddleware)

    response = TestClient(app).get("/auth/me")

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-a"
