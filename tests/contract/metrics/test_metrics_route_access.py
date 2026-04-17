from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.router import build_api_router
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware
from backend.observability.metrics import MetricsSnapshot


class _FakeSession:
    def execute(self, *_args, **_kwargs):
        class _Result:
            def scalar_one(self) -> int:
                return 1

        return _Result()


class _FakeDbRuntime:
    def session_scope(self):
        yield _FakeSession()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = MagicMock(
        oidc_jwks_uri="https://example/jwks", oidc_issuer="https://example", oidc_audience="ajenda"
    )
    app.state.database_runtime = _FakeDbRuntime()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(TenantContextMiddleware)
    app.include_router(build_api_router())
    return app


def test_rg_metrics_route_public_and_prometheus_text() -> None:
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch(
        "backend.api.routes.observability._collect_snapshot",
        return_value=MetricsSnapshot(1, 2, 3, 4, 5, 6, 1, 0.5),
    ):
        response = client.get("/v1/observability/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")
    assert "ajenda_tasks_queued" in response.text
