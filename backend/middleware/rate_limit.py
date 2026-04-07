"""Rate limiting middleware for Ajenda AI.

The limiter is configured from Settings (AJENDA_RATE_LIMIT_REQUESTS and
AJENDA_RATE_LIMIT_WINDOW_SECONDS) rather than hardcoded values. This allows
per-environment tuning without code changes:

  AJENDA_RATE_LIMIT_REQUESTS=200      # default: 100
  AJENDA_RATE_LIMIT_WINDOW_SECONDS=30 # default: 60

If a pre-built limiter is injected (e.g. in tests), it takes precedence over
the settings-derived defaults. This preserves full testability without
monkeypatching.

Rate limit decisions are keyed by (tenant_id, principal_id, route) so that
different tenants and principals have independent buckets.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.app.config import get_settings
from backend.rate_limit.limiter import RateLimiter, RateLimitKey


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: RateLimiter | None = None):
        super().__init__(app)
        if limiter is not None:
            # Injected limiter takes precedence (used in tests)
            self._limiter = limiter
        else:
            settings = get_settings()
            self._limiter = RateLimiter(
                max_requests=settings.rate_limit_requests,
                window_seconds=settings.rate_limit_window_seconds,
            )

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
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Limit"] = str(self._limiter.max_requests)
        return response
