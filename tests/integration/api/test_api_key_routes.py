from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from backend.api.routes.api_keys import router
from backend.app.dependencies.db import get_tenant_db_session
from backend.auth.principal import PrincipalType, UserPrincipal
from backend.middleware.tenant_context import TenantContextMiddleware

TENANT_ID = "11111111-1111-1111-1111-111111111111"


class PrincipalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = UserPrincipal(
            subject_id="user-1",
            tenant_id=TENANT_ID,
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)


def test_api_key_routes_create() -> None:
    app = FastAPI()
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    app.include_router(router)
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(PrincipalMiddleware)

    record = SimpleNamespace(
        key_id="key-1",
        tenant_id=TENANT_ID,
        scopes_json=["execution:queue"],
    )

    with (
        patch("backend.api.routes.api_keys.AuthorizationService") as authz_cls,
        patch("backend.api.routes.api_keys.ApiKeyService") as service_cls,
        patch("backend.api.routes.api_keys.QuotaEnforcementService") as quota_cls,
    ):
        authz_cls.return_value.require.return_value = None
        service = MagicMock()
        service.count_active_keys.return_value = 0
        service.create_key.return_value = ("secret", record)
        service_cls.return_value = service
        quota_cls.return_value.check_api_key_limit.return_value = None

        response = TestClient(app).post(
            "/api-keys",
            headers={"X-Tenant-Id": TENANT_ID},
            json={"scopes": ["execution:queue"]},
        )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == TENANT_ID
    assert response.json()["plaintext_key"] == "key-1.secret"
