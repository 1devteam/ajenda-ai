from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_TENANT_EXEMPT_PREFIXES = (
    "/health",
    "/readiness",
    "/ready",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth",
    "/system/health",
    "/system/readiness",
    "/v1/auth",
    "/v1/admin",
    "/v1/system/health",
    "/v1/system/readiness",
    "/v1/observability/metrics",
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extract tenant context while allowing public infrastructure paths."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        tenant_id = request.headers.get("X-Tenant-Id")
        path = request.url.path

        if tenant_id:
            request.state.tenant_id = tenant_id
        elif any(path.startswith(prefix) for prefix in _TENANT_EXEMPT_PREFIXES):
            request.state.tenant_id = None
        else:
            return JSONResponse(
                status_code=400,
                content={"detail": "X-Tenant-Id header required"},
            )

        return await call_next(request)
