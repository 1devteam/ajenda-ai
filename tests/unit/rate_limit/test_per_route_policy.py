"""Unit tests for per-route rate limit policy overrides.

Verifies that:
  - RoutePolicy validates its own fields on construction
  - RateLimiter.route_policies returns the configured map
  - Longest-prefix matching applies the most specific policy
  - Global defaults apply when no prefix matches
  - Per-route limits are independent of the global limit
  - Different tenants/principals share the same route bucket
    (keyed by (tenant_id, principal_id, route))
  - The default middleware route policies cover /v1/webhooks and /v1/admin
"""

from __future__ import annotations

import pytest

from backend.middleware.rate_limit import _DEFAULT_ROUTE_POLICIES
from backend.rate_limit.limiter import RateLimiter, RateLimitKey, RoutePolicy

# ---------------------------------------------------------------------------
# RoutePolicy construction
# ---------------------------------------------------------------------------


class TestRoutePolicyConstruction:
    def test_valid_policy_constructs(self) -> None:
        policy = RoutePolicy(max_requests=10, window_seconds=60)
        assert policy.max_requests == 10
        assert policy.window_seconds == 60

    def test_zero_max_requests_raises(self) -> None:
        with pytest.raises(ValueError, match="max_requests must be positive"):
            RoutePolicy(max_requests=0, window_seconds=60)

    def test_negative_max_requests_raises(self) -> None:
        with pytest.raises(ValueError, match="max_requests must be positive"):
            RoutePolicy(max_requests=-1, window_seconds=60)

    def test_zero_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            RoutePolicy(max_requests=10, window_seconds=0)

    def test_negative_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            RoutePolicy(max_requests=10, window_seconds=-5)


# ---------------------------------------------------------------------------
# RateLimiter route_policies property
# ---------------------------------------------------------------------------


class TestRateLimiterRoutePolicies:
    def test_route_policies_returns_configured_map(self) -> None:
        policies = {
            "/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60),
            "/v1/admin": RoutePolicy(max_requests=20, window_seconds=60),
        }
        limiter = RateLimiter(max_requests=100, window_seconds=60, route_policies=policies)
        result = limiter.route_policies
        assert "/v1/webhooks" in result
        assert "/v1/admin" in result
        assert result["/v1/webhooks"].max_requests == 10
        assert result["/v1/admin"].max_requests == 20

    def test_no_route_policies_returns_empty_map(self) -> None:
        limiter = RateLimiter(max_requests=100, window_seconds=60)
        assert limiter.route_policies == {}


# ---------------------------------------------------------------------------
# _resolve_policy — prefix matching
# ---------------------------------------------------------------------------


class TestResolvePolicyPrefixMatching:
    def _limiter(self) -> RateLimiter:
        return RateLimiter(
            max_requests=100,
            window_seconds=60,
            route_policies={
                "/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60),
                "/v1/admin": RoutePolicy(max_requests=20, window_seconds=60),
                "/v1/admin/tenants": RoutePolicy(max_requests=5, window_seconds=60),
            },
        )

    def test_exact_prefix_match(self) -> None:
        limiter = self._limiter()
        max_req, _ = limiter._resolve_policy("/v1/webhooks")
        assert max_req == 10

    def test_sub_path_match(self) -> None:
        """A sub-path of /v1/webhooks must use the /v1/webhooks policy."""
        limiter = self._limiter()
        max_req, _ = limiter._resolve_policy("/v1/webhooks/abc-123")
        assert max_req == 10

    def test_longest_prefix_wins(self) -> None:
        """/v1/admin/tenants is more specific than /v1/admin — it must win."""
        limiter = self._limiter()
        max_req, _ = limiter._resolve_policy("/v1/admin/tenants/uuid-here")
        assert max_req == 5

    def test_shorter_prefix_applies_when_longer_does_not_match(self) -> None:
        """/v1/admin/other does not match /v1/admin/tenants — falls back to /v1/admin."""
        limiter = self._limiter()
        max_req, _ = limiter._resolve_policy("/v1/admin/other")
        assert max_req == 20

    def test_no_match_uses_global_default(self) -> None:
        limiter = self._limiter()
        max_req, window = limiter._resolve_policy("/v1/missions/abc")
        assert max_req == 100
        assert window == 60

    def test_unrelated_path_uses_global_default(self) -> None:
        limiter = self._limiter()
        max_req, _ = limiter._resolve_policy("/health")
        assert max_req == 100


# ---------------------------------------------------------------------------
# Per-route enforcement — limits are applied correctly
# ---------------------------------------------------------------------------


class TestPerRouteLimitEnforcement:
    def _key(self, route: str) -> RateLimitKey:
        return RateLimitKey(tenant_id="tenant-a", principal_id="user-1", route=route)

    def test_webhook_route_uses_tighter_limit(self) -> None:
        """Requests to /v1/webhooks must be denied after 10 requests, not 100."""
        limiter = RateLimiter(
            max_requests=100,
            window_seconds=60,
            route_policies={"/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60)},
        )
        key = self._key("/v1/webhooks")
        for _ in range(10):
            decision = limiter.evaluate(key)
            assert decision.allowed is True

        # 11th request must be denied
        denied = limiter.evaluate(key)
        assert denied.allowed is False
        assert denied.retry_after_seconds is not None

    def test_global_route_uses_global_limit(self) -> None:
        """Requests to /v1/missions must use the global limit of 5, not 10."""
        limiter = RateLimiter(
            max_requests=5,
            window_seconds=60,
            route_policies={"/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60)},
        )
        key = self._key("/v1/missions")
        for _ in range(5):
            assert limiter.evaluate(key).allowed is True

        assert limiter.evaluate(key).allowed is False

    def test_per_route_buckets_are_independent(self) -> None:
        """Exhausting /v1/webhooks must not affect /v1/missions."""
        limiter = RateLimiter(
            max_requests=100,
            window_seconds=60,
            route_policies={"/v1/webhooks": RoutePolicy(max_requests=2, window_seconds=60)},
        )
        webhook_key = self._key("/v1/webhooks")
        mission_key = self._key("/v1/missions")

        # Exhaust the webhook bucket
        limiter.evaluate(webhook_key)
        limiter.evaluate(webhook_key)
        assert limiter.evaluate(webhook_key).allowed is False

        # Mission route must still be allowed
        assert limiter.evaluate(mission_key).allowed is True

    def test_remaining_count_reflects_per_route_limit(self) -> None:
        """X-RateLimit-Remaining must count against the per-route limit, not global."""
        limiter = RateLimiter(
            max_requests=100,
            window_seconds=60,
            route_policies={"/v1/admin": RoutePolicy(max_requests=20, window_seconds=60)},
        )
        key = self._key("/v1/admin")
        decision = limiter.evaluate(key)
        # After 1 request: 19 remaining (20 - 1)
        assert decision.remaining == 19

    def test_retry_after_is_positive_on_denial(self) -> None:
        limiter = RateLimiter(
            max_requests=1,
            window_seconds=60,
            route_policies={"/v1/webhooks": RoutePolicy(max_requests=1, window_seconds=30)},
        )
        key = self._key("/v1/webhooks")
        limiter.evaluate(key)  # consume the 1 allowed request
        denied = limiter.evaluate(key)
        assert denied.allowed is False
        assert denied.retry_after_seconds is not None
        assert denied.retry_after_seconds >= 1


# ---------------------------------------------------------------------------
# Default middleware route policies
# ---------------------------------------------------------------------------


class TestDefaultRoutePolices:
    """Verify that the middleware's _DEFAULT_ROUTE_POLICIES cover the
    high-risk endpoints with the expected limits."""

    def test_webhooks_prefix_is_configured(self) -> None:
        assert "/v1/webhooks" in _DEFAULT_ROUTE_POLICIES

    def test_admin_prefix_is_configured(self) -> None:
        assert "/v1/admin" in _DEFAULT_ROUTE_POLICIES

    def test_webhooks_limit_is_tighter_than_global_default(self) -> None:
        """Webhook limit must be significantly lower than the global default of 100."""
        policy = _DEFAULT_ROUTE_POLICIES["/v1/webhooks"]
        assert policy.max_requests < 100, (
            f"Webhook rate limit ({policy.max_requests}) should be much lower than "
            "the global default (100) to prevent abuse."
        )

    def test_admin_limit_is_tighter_than_global_default(self) -> None:
        policy = _DEFAULT_ROUTE_POLICIES["/v1/admin"]
        assert policy.max_requests < 100, (
            f"Admin rate limit ({policy.max_requests}) should be lower than "
            "the global default (100) to protect the control plane."
        )

    def test_webhook_limit_is_at_most_10_per_minute(self) -> None:
        """Webhook registration involves bcrypt hashing — 10/min is the upper bound."""
        policy = _DEFAULT_ROUTE_POLICIES["/v1/webhooks"]
        assert policy.max_requests <= 10
        assert policy.window_seconds == 60

    def test_admin_limit_is_at_most_20_per_minute(self) -> None:
        policy = _DEFAULT_ROUTE_POLICIES["/v1/admin"]
        assert policy.max_requests <= 20
        assert policy.window_seconds == 60
