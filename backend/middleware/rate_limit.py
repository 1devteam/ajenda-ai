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

import logging
from collections.abc import Awaitable, Callable

from prometheus_client import Counter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.rate_limit.limiter import RateLimiter, RateLimitKey, RoutePolicy
from backend.services.quota_enforcement import QuotaExceededError
from backend.utils.client_ip import extract_client_ip, hash_client_ip

_QUOTA_LOCK_TIMEOUT_MS = 5_000

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-route policy defaults (tunable via Settings in a future iteration)
# ---------------------------------------------------------------------------
_ONBOARDING_ROUTE_POLICIES: dict[str, RoutePolicy] = {
    "/v1/onboarding/signup": RoutePolicy(max_requests=5, window_seconds=3600),
    "/v1/onboarding/verify-email": RoutePolicy(max_requests=20, window_seconds=3600),
    "/v1/onboarding/resend-verification": RoutePolicy(max_requests=3, window_seconds=3600),
}

_DEFAULT_ROUTE_POLICIES: dict[str, RoutePolicy] = {
    # Webhook registration is expensive (bcrypt hash generation) and
    # abuse-prone (external HTTP calls on dispatch). Tighten significantly.
    "/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60),
    # Admin control plane: low expected volume, high blast-radius operations.
    "/v1/admin": RoutePolicy(max_requests=20, window_seconds=60),
    # Stripe webhook retries can burst; allow higher anonymous throughput.
    "/v1/billing/webhook/": RoutePolicy(max_requests=200, window_seconds=60),
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

_RATE_LIMIT_DECISIONS = Counter(
    "ajenda_rate_limit_decisions_total",
    "Rate-limit decisions by plan, route class, and outcome.",
    ("plan", "route_class", "outcome"),
)


def _classify_route(path: str) -> str:
    if path.startswith("/v1/admin"):
        return "admin"
    if path.startswith("/v1/webhooks"):
        return "webhooks"
    if path.startswith("/v1/billing/webhook/"):
        return "stripe_webhook"
    if path.startswith("/v1/onboarding/"):
        return "onboarding"
    return "default"


def _onboarding_route_policy(path: str, settings: Settings) -> RoutePolicy | None:
    for prefix, policy in _ONBOARDING_ROUTE_POLICIES.items():
        if path.startswith(prefix):
            return RoutePolicy(
                max_requests=settings.signup_ip_limit_per_hour,
                window_seconds=policy.window_seconds,
            )
    return None


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
        settings = get_settings()
        principal = getattr(request.state, "principal", None)
        tenant_id = getattr(request.state, "tenant_id", None) or "anonymous"
        principal_id = getattr(principal, "subject_id", "anonymous")
        tenant = getattr(request.state, "tenant", None)
        plan_slug = getattr(tenant, "plan", None)
        plan_label = str(plan_slug) if plan_slug else "unknown"
        route_class = _classify_route(request.url.path)
        path = request.url.path
        if route_class == "onboarding":
            client_ip_hash = hash_client_ip(extract_client_ip(request))
            key = RateLimitKey(
                tenant_id="onboarding",
                principal_id=client_ip_hash,
                route=path,
            )
        else:
            key = RateLimitKey(
                tenant_id=tenant_id,
                principal_id=principal_id,
                route=path,
            )
        onboarding_policy = _onboarding_route_policy(path, settings)
        if onboarding_policy is not None:
            base_max, base_window = onboarding_policy.max_requests, onboarding_policy.window_seconds
        else:
            base_max, base_window = self._limiter._resolve_policy(path)
        multiplier = _PLAN_RATE_MULTIPLIER.get(str(plan_slug), 1.0)
        burst_credit = _PLAN_BURST_CREDIT.get(str(plan_slug), 0)
        effective_max = max(1, int(base_max * multiplier) + burst_credit)
        decision = self._limiter.evaluate_with_policy(
            key,
            max_requests=effective_max,
            window_seconds=base_window,
        )
        if not decision.allowed:
            _RATE_LIMIT_DECISIONS.labels(plan=plan_label, route_class=route_class, outcome="denied").inc()
            logger.info(
                "rate_limit_decision",
                extra={
                    "allowed": False,
                    "tenant_id": tenant_id,
                    "plan": plan_label,
                    "route_class": route_class,
                    "route": request.url.path,
                    "effective_limit": effective_max,
                    "retry_after_seconds": decision.retry_after_seconds,
                },
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded", "retry_after": decision.retry_after_seconds},
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )

        # PR5: enforce api_calls quota before handlers run so over-limit tenants
        # cannot mutate state or queue work before admission is denied.
        if tenant_id and tenant_id != "anonymous":
            quota_response = self._enforce_api_call_quota_admission(request, tenant_id)
            if quota_response is not None:
                return quota_response

        response = await call_next(request)
        _RATE_LIMIT_DECISIONS.labels(plan=plan_label, route_class=route_class, outcome="allowed").inc()
        logger.info(
            "rate_limit_decision",
            extra={
                "allowed": True,
                "tenant_id": tenant_id,
                "plan": plan_label,
                "route_class": route_class,
                "route": request.url.path,
                "effective_limit": effective_max,
                "remaining": decision.remaining,
            },
        )
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Limit"] = str(effective_max)
        if plan_slug:
            response.headers["X-RateLimit-Plan"] = str(plan_slug)

        if tenant_id and tenant_id != "anonymous" and 200 <= response.status_code < 400:
            self._record_api_call_usage(request, tenant_id)
        return response

    def _configure_quota_session(self, session: Session) -> None:
        session.execute(text(f"SET LOCAL lock_timeout = '{_QUOTA_LOCK_TIMEOUT_MS}ms'"))

    def _quota_exceeded_response(self, exc: QuotaExceededError) -> JSONResponse:
        return JSONResponse(
            status_code=402,
            content={
                "code": "QUOTA_EXCEEDED",
                "field": exc.field,
                "limit": exc.limit,
                "current": exc.current,
                "plan": exc.plan,
                "message": (
                    f"You have reached the {exc.field} limit ({exc.limit}) "
                    f"for the {exc.plan!r} plan. Upgrade to continue."
                ),
            },
        )

    def _enforce_api_call_quota_admission(self, request: Request, tenant_id: str) -> JSONResponse | None:
        try:
            database_runtime = getattr(request.app.state, "database_runtime", None)
            if database_runtime is None:
                return None
            session = database_runtime.session_factory()
            try:
                from uuid import UUID

                from backend.services.quota_enforcement import QuotaEnforcementService

                self._configure_quota_session(session)
                quota = QuotaEnforcementService(session)
                quota.check_api_call_quota(UUID(tenant_id))
                session.commit()
            except QuotaExceededError as exc:
                session.rollback()
                return self._quota_exceeded_response(exc)
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception:
            return None
        return None

    def _record_api_call_usage(self, request: Request, tenant_id: str) -> None:
        try:
            database_runtime = getattr(request.app.state, "database_runtime", None)
            if database_runtime is None:
                return
            session = database_runtime.session_factory()
            try:
                from uuid import UUID

                from backend.services.quota_enforcement import QuotaEnforcementService

                self._configure_quota_session(session)
                quota = QuotaEnforcementService(session)
                quota.record_api_call(UUID(tenant_id))
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()
        except Exception:
            pass
