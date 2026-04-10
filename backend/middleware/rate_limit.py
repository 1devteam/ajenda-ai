"""Rate limiting middleware for Ajenda AI.

The limiter is configured from Settings (AJENDA_RATE_LIMIT_REQUESTS and
AJENDA_RATE_LIMIT_WINDOW_SECONDS) rather than hardcoded values. This allows
per-environment tuning without code changes:

  AJENDA_RATE_LIMIT_REQUESTS=200      # default: 100
  AJENDA_RATE_LIMIT_WINDOW_SECONDS=30 # default: 60

Per-route overrides are applied for high-risk endpoints:

  /v1/webhooks  — 10 req/60s  (webhook registration is expensive and abuse-prone)
  /v1/admin     — 20 req/60s  (admin control plane; low expected volume)

If a pre-built limiter is injected (e.g. in tests), it takes precedence over
the settings-derived defaults. This preserves full testability without
monkeypatching.

Rate limit decisions are keyed by (tenant_id, principal_id, route) so that
different tenants and principals have independent buckets.

Response headers
----------------
  X-RateLimit-Limit     — effective limit for this route
  X-RateLimit-Remaining — requests remaining in the current window
  Retry-After           — seconds until the window resets (only on 429)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from backend.app.config import get_settings
from backend.rate_limit.limiter import RateLimiter, RateLimitKey, RoutePolicy

# ---------------------------------------------------------------------------
# Per-route policy defaults (tunable via Settings in a future iteration)
# ---------------------------------------------------------------------------
_DEFAULT_ROUTE_POLICIES: dict[str, RoutePolicy] = {
    # Webhook registration is expensive (bcrypt hash generation) and
    # abuse-prone (external HTTP calls on dispatch). Tighten significantly.
    "/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60),
    # Admin control plane: low expected volume, high blast-radius operations.
    "/v1/admin": RoutePolicy(max_requests=20, window_seconds=60),
}

# Plan-aware adaptive policy:
# - multiplier scales baseline route/global limits
# - burst_credit adds a small fixed premium for short spikes
# This is the first implementation step for tenant-aware adaptive limiting.
_PLAN_RATE_MULTIPLIER: dict[str, float] = {
    "free": 1.0,
    "starter": 1.25,
    "pro": 1.75,
    "enterprise": 2.5,
}
_PLAN_BURST_CREDIT: dict[str, int] = {
    "free": 0,
    "starter": 2,
    "pro": 5,
    "enterprise": 10,
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, limiter: RateLimiter | None = None) -> None:
        super().__init__(app)
        if limiter is not None:
            # Injected limiter takes precedence (used in tests)
            self._limiter = limiter
        else:
            settings = get_settings()
            self._limiter = RateLimiter(
                max_requests=settings.rate_limit_requests,
                window_seconds=settings.rate_limit_window_seconds,
                route_policies=_DEFAULT_ROUTE_POLICIES,
            )

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        principal = getattr(request.state, "principal", None)
        tenant_id = getattr(request.state, "tenant_id", None) or "anonymous"
        principal_id = getattr(principal, "subject_id", "anonymous")
        tenant = getattr(request.state, "tenant", None)
        plan_slug = getattr(tenant, "plan", None)
        key = RateLimitKey(
            tenant_id=tenant_id,
            principal_id=principal_id,
            route=request.url.path,
        )
        # Resolve baseline route policy, then adapt by tenant plan.
        base_max, base_window = self._limiter._resolve_policy(request.url.path)
        multiplier = _PLAN_RATE_MULTIPLIER.get(str(plan_slug), 1.0)
        burst_credit = _PLAN_BURST_CREDIT.get(str(plan_slug), 0)
        effective_max = max(1, int(base_max * multiplier) + burst_credit)
        decision = self._limiter.evaluate_with_policy(
            key,
            max_requests=effective_max,
            window_seconds=base_window,
        )
        if not decision.allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": decision.retry_after_seconds},
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Limit"] = str(effective_max)
        if plan_slug:
            response.headers["X-RateLimit-Plan"] = str(plan_slug)
        return response
