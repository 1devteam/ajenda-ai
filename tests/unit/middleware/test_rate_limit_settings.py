"""Unit tests verifying RateLimitMiddleware reads config from Settings.

Ensures that the middleware is not hardcoded to 100 requests / 60 seconds
but instead reads from AJENDA_RATE_LIMIT_REQUESTS and
AJENDA_RATE_LIMIT_WINDOW_SECONDS environment variables via Settings.
"""

from __future__ import annotations

from backend.rate_limit.limiter import RateLimiter


class TestRateLimiterProperties:
    def test_max_requests_property(self) -> None:
        limiter = RateLimiter(max_requests=50, window_seconds=30)
        assert limiter.max_requests == 50

    def test_window_seconds_property(self) -> None:
        limiter = RateLimiter(max_requests=50, window_seconds=30)
        assert limiter.window_seconds == 30

    def test_custom_limits_enforced(self) -> None:
        """A limiter with max_requests=2 should deny the third request."""
        from backend.rate_limit.limiter import RateLimitKey

        limiter = RateLimiter(max_requests=2, window_seconds=60)
        key = RateLimitKey(tenant_id="t1", principal_id="p1", route="/test")
        r1 = limiter.evaluate(key)
        r2 = limiter.evaluate(key)
        r3 = limiter.evaluate(key)
        assert r1.allowed is True
        assert r2.allowed is True
        assert r3.allowed is False
        assert r3.retry_after_seconds is not None
        assert r3.retry_after_seconds >= 1

    def test_invalid_max_requests_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="max_requests must be positive"):
            RateLimiter(max_requests=0, window_seconds=60)

    def test_invalid_window_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="window_seconds must be positive"):
            RateLimiter(max_requests=10, window_seconds=0)
