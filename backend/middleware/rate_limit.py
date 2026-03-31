from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.rate_limit.limiter import RateLimitKey, RateLimiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        self._limiter = limiter or RateLimiter(max_requests=100, window_seconds=60)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        principal = getattr(request.state, "principal", None)
        tenant_id = getattr(request.state, "tenant_id", None) or "anonymous"
        principal_id = getattr(principal, "subject_id", "anonymous")
        decision = self._limiter.evaluate(
            RateLimitKey(
                tenant_id=tenant_id,
                principal_id=principal_id,
                route=request.url.path,
            )
        )
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": decision.retry_after_seconds},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response
