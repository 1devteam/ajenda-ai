from backend.rate_limit.limiter import RateLimiter, RateLimitKey


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    key = RateLimitKey("tenant-a", "user-1", "/x")
    assert limiter.evaluate(key).allowed is True
    assert limiter.evaluate(key).allowed is False


def test_evaluate_with_policy_supports_explicit_dynamic_limits() -> None:
    limiter = RateLimiter(max_requests=100, window_seconds=60)
    key = RateLimitKey("tenant-a", "user-1", "/x")
    assert limiter.evaluate_with_policy(key, max_requests=2, window_seconds=60).allowed is True
    assert limiter.evaluate_with_policy(key, max_requests=2, window_seconds=60).allowed is True
    assert limiter.evaluate_with_policy(key, max_requests=2, window_seconds=60).allowed is False
