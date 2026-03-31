from __future__ import annotations

from collections.abc import Callable
from typing import Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        tenant_id = request.headers.get("X-Tenant-Id")
        if tenant_id:
            request.state.tenant_id = tenant_id
        elif request.url.path.startswith("/auth") or request.url.path.startswith("/api-keys"):
            request.state.tenant_id = None
        else:
            return JSONResponse(status_code=400, content={"detail": "X-Tenant-Id header required"})
        return await call_next(request)
