from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.request_id = str(uuid.uuid4())
        return await call_next(request)
