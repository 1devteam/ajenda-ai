from __future__ import annotations

from collections.abc import Callable
from typing import Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths that do not require a tenant context.
# Health/readiness probes, metrics scraping, and auth flows must never
# be blocked by a missing X-Tenant-Id header.
_TENANT_EXEMPT_PREFIXES = (
    "/health",
    "/ready",
    "/metrics",
    "/system/health",
    "/auth",
    "/api-keys",
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extracts and validates the X-Tenant-Id header for all tenant-scoped requests.

    Public paths (health probes, metrics, auth flows) are exempt from the
    tenant header requirement. All other paths return HTTP 400 if the header
    is missing.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        tenant_id = request.headers.get("X-Tenant-Id")

        if tenant_id:
            request.state.tenant_id = tenant_id
        elif any(path.startswith(prefix) for prefix in _TENANT_EXEMPT_PREFIXES):
            # Public path — tenant context is not required
            request.state.tenant_id = None
        else:
            return JSONResponse(
                status_code=400,
                content={"detail": "X-Tenant-Id header required"},
            )

        return await call_next(request)
