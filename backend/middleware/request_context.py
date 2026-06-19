from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.observability.context import set_correlation_id, set_tenant_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        set_correlation_id(request_id)
        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id:
            set_tenant_id(str(tenant_id))
        return await call_next(request)
