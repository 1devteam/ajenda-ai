from __future__ import annotations

from starlette.middleware.cors import CORSMiddleware

from backend.main import create_app
from backend.middleware.auth_context import AuthContextMiddleware
from backend.middleware.idempotency import IdempotencyMiddleware
from backend.middleware.rate_limit import RateLimitMiddleware
from backend.middleware.request_context import RequestContextMiddleware
from backend.middleware.security_headers import SecurityHeadersMiddleware
from backend.middleware.tenant_context import TenantContextMiddleware


def test_middleware_registration_preserves_tenant_auth_and_idempotency_before_rate_limit() -> None:
    app = create_app()

    assert [entry.cls for entry in app.user_middleware] == [
        SecurityHeadersMiddleware,
        CORSMiddleware,
        TenantContextMiddleware,
        AuthContextMiddleware,
        IdempotencyMiddleware,
        RateLimitMiddleware,
        RequestContextMiddleware,
    ]
